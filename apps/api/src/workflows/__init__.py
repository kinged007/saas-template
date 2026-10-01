"""Subscriber-side workflows: consume domain events and produce side effects.

Workflows open their own DB session per event (they may run in a separate
process in production), so they never depend on request-scoped dependencies.

Registered subscriptions (subject → handler, fanout flag):

  Durable (load-balanced across replicas, persisted in JetStream):
    workspaces.member.invited       → persist Notification row
    workspaces.member.joined        → notify inviter + other active members
    workspaces.member.role_changed  → notify the member whose role changed
    workspaces.member.removed       → notify the removed member
    workspaces.invitation.created   → email invite to unregistered recipients
    workspaces.created              → provisioning/analytics hook (TODO)
    audit.entry.created             → persist AuditLogEntry row
    apikeys.created                 → security/monitoring hook (TODO)
    apikeys.revoked                 → security/monitoring hook (TODO)
    jobs.execute                    → execute one scheduled-job run
    conversations.message.created   → persist notification pointers (bulk)

  Fanout (every replica receives the event, realtime push):
    notifications.created           → push to the user's WebSocket sessions
    conversations.message.live      → push thread update to participants
    conversations.renamed           → push title change to participants

The durable subscriptions run once per deployment (JetStream queue group);
the fanout subscription runs in *every* replica so the WS push reaches the
user regardless of which replica holds their socket.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from src.core.security.crypto import SecretCipher
from src.db.session import SessionFactory
from src.events.bus import EventBus
from src.events.factory import WorkflowRegistry
from src.events.publisher import publish_audit
from src.events.subjects import Subjects
from src.jobs.executor import execute_run
from src.models.workspace import WorkspaceMember
from src.realtime.manager import ConnectionManager
from src.services.audit import AuditService
from src.services.jobs import JobService
from src.services.notifications import NotificationService

logger = logging.getLogger(__name__)

# Frontend route the invitation notification's "Open" button links to. The dev
# seed (src/seed.py) imports it, so the two payload sides cannot drift.
INVITATIONS_ROUTE = "/invitations"


async def _audit_email_failure(
    bus: EventBus,
    notification,
    *,
    correlation_id: str | None,
    user_id: str,
    n_type: str,
    email: str | None,
    reason: str,
) -> None:
    """Log and audit one notification email that was not delivered.

    `reason` is `no_recipient`, `no_email` or `send_failed`. Published after
    the attempt, so a failing publish nacks the message and the in-app
    notification row is created again on redelivery.
    """
    logger.error(
        "notification email failed for %s (notification %s, reason=%s)",
        email or f"user {user_id}",
        notification.id,
        reason,
    )
    await publish_audit(
        bus,
        correlation_id=correlation_id,
        workspace_id=notification.workspace_id,
        resource_type="notification",
        resource_id=notification.id,
        action="notification.email_failed",
        details={"user_id": user_id, "type": n_type, "email": email, "reason": reason},
    )


async def _create_notification(
    session, bus: EventBus, *, correlation_id: str | None = None, **kwargs
) -> None:
    """Persist a notification and fan it out over the bus in one call.

    Honors the recipient's channel preference: `off` skips the insert;
    `email` inserts and sends an immediate email, fail-closed (the in-app
    row is kept and the failure logged and audited
    (`notification.email_failed`) when the recipient is missing, has no
    address, or sending fails).
    """
    service = NotificationService(session, bus)
    n_type = kwargs.get("type", "")
    n_user_id = kwargs.get("user_id")
    channel = await service.resolve_channel(n_user_id, n_type) if n_user_id else "in-app"
    if channel == "off":
        return
    notification = await service.create(**kwargs, correlation_id=correlation_id)
    if channel != "email":
        return
    from src.email.factory import send_email
    from src.email.templates import notification_email
    from src.models.workspace import User
    from src.services.notifications import unsubscribe_url_for
    from src.settings import settings

    recipient = await session.get(User, n_user_id)
    if recipient is None or not recipient.email:
        await _audit_email_failure(
            bus,
            notification,
            correlation_id=correlation_id,
            user_id=n_user_id,
            n_type=n_type,
            email=recipient.email if recipient else None,
            reason="no_recipient" if recipient is None else "no_email",
        )
        return
    token = await service.token_for(n_user_id, n_type)
    sent = await send_email(
        notification_email(
            recipient.email,
            title=notification.title,
            body=notification.body,
            workspace_name=(notification.payload or {}).get("workspace_name", ""),
            unsubscribe_url=unsubscribe_url_for(token or "", n_type, settings.frontend_url),
        )
    )
    if sent:
        return
    await _audit_email_failure(
        bus,
        notification,
        correlation_id=correlation_id,
        user_id=n_user_id,
        n_type=n_type,
        email=recipient.email,
        reason="send_failed",
    )


def build_workflows(
    registry: WorkflowRegistry,
    bus: EventBus,
    connection_manager: ConnectionManager,
    cipher: SecretCipher | None = None,
) -> None:
    async def on_member_invited(payload: dict, metadata) -> None:
        user_id = payload.get("user_id")
        if not user_id:
            return
        async with SessionFactory() as session:
            await _create_notification(
                session,
                bus,
                user_id=user_id,
                workspace_id=payload.get("workspace_id"),
                type="workspace_invitation",
                title=payload.get("title", "You were invited to a workspace"),
                body=payload.get("body", ""),
                metadata={
                    "workspace_id": payload.get("workspace_id"),
                    "workspace_name": payload.get("workspace_name"),
                    "invitation_id": payload.get("invitation_id"),
                    "invited_by": payload.get("invited_by"),
                    # NotificationCenter renders an "Open" button only when
                    # the payload carries a url; without it the invite is a
                    # dead end.
                    "url": INVITATIONS_ROUTE,
                },
                correlation_id=metadata.correlation_id,
            )
        logger.info("notification persisted for user %s (%s)", user_id, payload.get("workspace_id"))

    async def on_member_joined(payload: dict, metadata) -> None:
        """Notify the inviter and the other active members that a user joined."""
        workspace_id = payload.get("workspace_id")
        user_id = payload.get("user_id")
        if not workspace_id or not user_id:
            return
        invited_by = payload.get("invited_by_user_id")
        workspace_name = payload.get("workspace_name", "workspace")
        joiner_name = payload.get("user_name", "A member")
        async with SessionFactory() as session:
            if invited_by and invited_by != user_id:
                await _create_notification(
                    session,
                    bus,
                    user_id=invited_by,
                    workspace_id=workspace_id,
                    type="member_joined",
                    title=f"{joiner_name} joined {workspace_name}",
                    body=(
                        f"{joiner_name} accepted your invitation to the {workspace_name} workspace."
                    ),
                    metadata={
                        "workspace_id": workspace_id,
                        "workspace_name": workspace_name,
                        "user_id": user_id,
                    },
                    correlation_id=metadata.correlation_id,
                )
            result = await session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.status == "active",
                )
            )
            for member in result.scalars().all():
                if member.user_id in (user_id, invited_by):
                    continue
                await _create_notification(
                    session,
                    bus,
                    user_id=member.user_id,
                    workspace_id=workspace_id,
                    type="member_joined",
                    title=f"{joiner_name} joined {workspace_name}",
                    body=f"{joiner_name} joined the {workspace_name} workspace.",
                    metadata={
                        "workspace_id": workspace_id,
                        "workspace_name": workspace_name,
                        "user_id": user_id,
                    },
                    correlation_id=metadata.correlation_id,
                )

    async def on_member_role_changed(payload: dict, metadata) -> None:
        user_id = payload.get("user_id")
        workspace_id = payload.get("workspace_id")
        if not user_id or not workspace_id:
            return
        workspace_name = payload.get("workspace_name", "workspace")
        from_role = payload.get("from_role") or "unknown"
        to_role = payload.get("to_role") or "unknown"
        changed_by = payload.get("changed_by_name") or "A member"
        # The member is the actor (a self-demotion, or an ownership transfer):
        # naming them in their own notification reads as "you changed your
        # own role". set_member_role refuses to touch the owner's role, so a
        # self-change from owner is always a transfer.
        if user_id == payload.get("changed_by_user_id"):
            body = (
                f"You transferred ownership. Your role is now {to_role}."
                if from_role == "owner"
                else f"Your role is now {to_role}."
            )
        else:
            body = f"{changed_by} changed your role from {from_role} to {to_role}."
        async with SessionFactory() as session:
            await _create_notification(
                session,
                bus,
                user_id=user_id,
                workspace_id=workspace_id,
                type="member_role_changed",
                title=f"Your role changed in {workspace_name}",
                body=body,
                metadata={
                    "workspace_id": workspace_id,
                    "workspace_name": workspace_name,
                    "from_role": payload.get("from_role"),
                    "to_role": payload.get("to_role"),
                    "changed_by": changed_by,
                },
                correlation_id=metadata.correlation_id,
            )

    async def on_member_removed(payload: dict, metadata) -> None:
        user_id = payload.get("user_id")
        workspace_id = payload.get("workspace_id")
        if not user_id or not workspace_id:
            return
        workspace_name = payload.get("workspace_name", "workspace")
        removed_by = payload.get("removed_by_name", "An administrator")
        async with SessionFactory() as session:
            await _create_notification(
                session,
                bus,
                user_id=user_id,
                workspace_id=workspace_id,
                type="member_removed",
                title=f"You were removed from {workspace_name}",
                body=f"{removed_by} removed you from the {workspace_name} workspace.",
                metadata={
                    "workspace_id": workspace_id,
                    "workspace_name": workspace_name,
                    "removed_by": removed_by,
                },
                correlation_id=metadata.correlation_id,
            )

    async def on_invitation_created(payload: dict, metadata) -> None:
        """Email unregistered recipients their invite link (fail-closed)."""
        if payload.get("is_registered"):
            return
        email = payload.get("email")
        if not email:
            return
        from src.email.factory import send_email
        from src.email.templates import invitation as invitation_template
        from src.settings import settings

        # The token stays out of the published payload: `invitation.created` is
        # a public webhook event, so a token here would be delivered to every
        # workspace webhook subscriber. It is re-read from the committed row.
        token = ""
        invitation_id = payload.get("invitation_id")
        if invitation_id:
            async with SessionFactory() as session:
                from src.models.core import Invitation

                invite = await session.get(Invitation, invitation_id)
                if invite is not None:
                    token = invite.token
        invite_url = (
            f"{settings.frontend_url.rstrip('/')}/invitations/accept?token={token}"
            if token
            else f"{settings.frontend_url.rstrip('/')}/invitations"
        )
        try:
            await send_email(
                invitation_template(
                    email,
                    workspace_name=payload.get("workspace_name", "workspace"),
                    invite_url=invite_url,
                    invited_by=payload.get("invited_by_name", ""),
                )
            )
        except Exception:
            logger.exception("invitation email failed for %s", email)

    async def on_workspace_created(payload: dict, metadata) -> None:
        """Provision workspace-scoped scheduled jobs for the new workspace.

        TODO(events): other provisioning/analytics hooks can live here too.
        """
        workspace_id = payload.get("workspace_id")
        if not workspace_id:
            return
        async with SessionFactory() as session:
            await JobService(session, bus, cipher).sync_definitions(workspace_ids=[workspace_id])
        logger.info(
            "workspace.created: %s (%s) by %s",
            payload.get("workspace_id"),
            payload.get("name"),
            payload.get("created_by_user_id"),
        )

    async def on_audit_entry(payload: dict, metadata) -> None:
        async with SessionFactory() as session:
            service = AuditService(session)
            await service.record(
                workspace_id=payload.get("workspace_id"),
                resource_type=payload["resource_type"],
                resource_id=payload["resource_id"],
                action=payload["action"],
                actor_user_id=payload.get("actor_user_id"),
                details=payload.get("details"),
                ip_address=payload.get("ip_address"),
            )
        logger.debug("audit entry persisted: %s", payload.get("action"))

    async def on_apikey_created(payload: dict, metadata) -> None:
        """Placeholder for key lifecycle consumers (security monitoring,
        audit dashboards, notifications to admins).

        TODO(events): implement consumption of apikeys.created.
        """
        logger.info(
            "apikey.created: %s (%s) in workspace %s by %s",
            payload.get("apikey_id"),
            payload.get("name"),
            payload.get("workspace_id"),
            payload.get("created_by_user_id"),
        )

    async def on_apikey_updated(payload: dict, metadata) -> None:
        """Placeholder for key lifecycle consumers (security monitoring,
        audit dashboards, notifications to admins).

        TODO(events): implement consumption of apikeys.updated.
        """
        logger.info(
            "apikey.updated: %s (%s) in workspace %s quota=%s by %s",
            payload.get("apikey_id"),
            payload.get("name"),
            payload.get("workspace_id"),
            payload.get("usage_quota"),
            payload.get("updated_by_user_id"),
        )

    async def on_apikey_revoked(payload: dict, metadata) -> None:
        """Placeholder for key lifecycle consumers (security monitoring,
        audit dashboards, notifications to admins).

        TODO(events): implement consumption of apikeys.revoked.
        """
        logger.info(
            "apikey.revoked: %s (%s) in workspace %s",
            payload.get("apikey_id"),
            payload.get("name"),
            payload.get("workspace_id"),
        )

    async def on_notification_created(payload: dict, metadata) -> None:
        """Realtime fan-out: push every new notification to live sessions."""
        user_id = payload.get("user_id")
        if not user_id:
            return
        await connection_manager.push(user_id=user_id, payload=payload)

    async def on_conversation_message(payload: dict, metadata) -> None:
        """Durable consumer: persist notification pointers in one bulk transaction.

        Realtime thread push is NOT done here — the durable consumer is
        load-balanced (one replica), while `ConnectionManager` sessions are
        per-process. The thread push happens in `on_conversation_message_live`
        (fanout) so every replica forwards to its own sessions.
        """
        workspace_id = payload.get("workspace_id")
        conversation_id = payload.get("conversation_id")
        sender_id = payload.get("sender_id")
        sender_type = payload.get("sender_type", "user")
        participant_ids: list[str] = payload.get("participant_user_ids") or []

        if not workspace_id or not conversation_id or not participant_ids:
            return

        recipients = [uid for uid in participant_ids if uid != sender_id or sender_type != "user"]
        if not recipients:
            return
        # Honor per-user channel prefs: `off` recipients get no pointer row.
        # conversation_message pointers never get immediate email (surfaced
        # via thread unread counts instead); digests exclude them too.
        from src.models.core import NotificationPreference

        async with SessionFactory() as _pref_session:
            pref_rows = (
                (
                    await _pref_session.execute(
                        select(NotificationPreference).where(
                            NotificationPreference.user_id.in_(recipients),
                            NotificationPreference.type == "conversation_message",
                        )
                    )
                )
                .scalars()
                .all()
            )
        off = {p.user_id for p in pref_rows if p.channel == "off"}
        recipients = [uid for uid in recipients if uid not in off]
        if not recipients:
            return
        title = payload.get("title") or payload.get("workspace_name") or "New message"
        workspace_name = payload.get("workspace_name", "workspace")
        async with SessionFactory() as session:
            await NotificationService(session, bus).create_many(
                [
                    {
                        "user_id": uid,
                        "workspace_id": workspace_id,
                        "type": "conversation_message",
                        "title": title,
                        "body": payload.get("body_preview", ""),
                        "metadata": {
                            "workspace_id": workspace_id,
                            "workspace_name": workspace_name,
                            "conversation_id": conversation_id,
                            "message_id": payload.get("message_id"),
                            "sender_id": sender_id,
                            "sender_name": payload.get("sender_name", "Someone"),
                        },
                    }
                    for uid in recipients
                ],
                correlation_id=metadata.correlation_id,
            )

    async def on_conversation_message_live(payload: dict, metadata) -> None:
        """Fanout consumer: push the message thread update to local sessions.

        Registered in every replica, so users receive `message.created`
        regardless of which replica holds their WebSocket.
        """
        participant_ids: list[str] = payload.get("participant_user_ids") or []
        if not participant_ids:
            return
        await connection_manager.push_many(
            participant_ids,
            payload,
            event="message.created",
        )

    async def on_conversation_renamed(payload: dict, metadata) -> None:
        """Fan-out conversation rename to participants."""

        participant_ids: list[str] | None = payload.get("participant_user_ids")
        # If payload does not contain participant list (legacy service path
        # with just workspace_id), fall back to no fan-out
        # New service publishes without participant list for rename; we need
        # to resolve participants from DB.
        if participant_ids is None:
            conversation_id = payload.get("conversation_id")
            if not conversation_id:
                return
            async with SessionFactory() as session:
                from src.models.conversation import ConversationParticipant

                result = await session.execute(
                    select(ConversationParticipant.participant_id).where(
                        ConversationParticipant.conversation_id == conversation_id,
                        ConversationParticipant.participant_type == "user",
                    )
                )
                participant_ids = [r[0] for r in result.all()]

        if not participant_ids:
            return
        await connection_manager.push_many(
            participant_ids,
            payload,
            event="conversation.renamed",
        )

    async def on_job_execute(payload: dict, metadata) -> None:
        """Execute one scheduled-job run (durable, load-balanced consumer).

        The executor claims the run atomically before running it, so bus
        redeliveries or extra replicas never duplicate an execution.
        """
        run_id = payload.get("run_id")
        if not run_id:
            return
        await execute_run(run_id, bus=bus)

    async def _fan_out_webhooks(payload: dict, metadata) -> None:
        """Fan one domain event out into pending webhook deliveries.

        Called at the top of every durable domain handler with a registered
        webhook event (one subscription per subject exists, so the fan-out
        chains off the existing handlers instead of adding its own). Failures
        stay pending for the dispatcher retry tick.
        """
        from src.secrets.factory import build_secret_store
        from src.services.webhooks import dispatch_due, fan_out_event

        async with SessionFactory() as session:
            count = await fan_out_event(
                session,
                subject=metadata.subject,
                payload=payload,
                event_id=metadata.event_id,
                correlation_id=metadata.correlation_id,
                occurred_at=metadata.occurred_at,
            )
        if not count:
            return
        # Best-effort immediate dispatch so the first attempt does not wait
        # for the dispatcher tick; failures stay pending for retry.
        try:
            async with SessionFactory() as session:
                await dispatch_due(session, build_secret_store())
        except Exception:
            logger.exception("webhook immediate dispatch failed")

    def _with_webhooks(handler):
        """Chain webhook fan-out off an existing durable handler.

        The registry allows one handler per subject, so deliverable domain
        events fan out from inside the existing handlers instead of adding
        their own subscriptions (which would double-consume or collide).
        """

        async def wrapped(payload: dict, metadata) -> None:
            await _fan_out_webhooks(payload, metadata)
            await handler(payload, metadata)

        return wrapped

    _hooked = _with_webhooks
    registry.register(Subjects.WORKSPACE_MEMBER_INVITED, _hooked(on_member_invited))
    registry.register(Subjects.WORKSPACE_MEMBER_JOINED, _hooked(on_member_joined))
    registry.register(Subjects.WORKSPACE_MEMBER_ROLE_CHANGED, _hooked(on_member_role_changed))
    registry.register(Subjects.WORKSPACE_MEMBER_REMOVED, _hooked(on_member_removed))
    registry.register(Subjects.WORKSPACE_INVITATION_CREATED, _hooked(on_invitation_created))
    registry.register(Subjects.WORKSPACE_CREATED, _hooked(on_workspace_created))
    registry.register(Subjects.AUDIT_ENTRY_CREATED, _hooked(on_audit_entry))
    registry.register(Subjects.APIKEY_CREATED, _hooked(on_apikey_created))
    registry.register(Subjects.APIKEY_REVOKED, _hooked(on_apikey_revoked))
    registry.register(Subjects.APIKEY_UPDATED, _hooked(on_apikey_updated))
    registry.register(Subjects.JOBS_EXECUTE, on_job_execute)
    registry.register(Subjects.NOTIFICATIONS_CREATED, on_notification_created, fanout=True)
    registry.register(Subjects.CONVERSATION_MESSAGE_CREATED, _hooked(on_conversation_message))
    registry.register(Subjects.CONVERSATION_MESSAGE_LIVE, on_conversation_message_live, fanout=True)
    registry.register(Subjects.CONVERSATION_RENAMED, on_conversation_renamed, fanout=True)
