"""Subscriber-side workflows: consume domain events and produce side effects.

Workflows open their own DB session per event (they may run in a separate
process in production), so they never depend on request-scoped dependencies.

Registered subscriptions (subject → handler, fanout flag):

  Durable (load-balanced across replicas, persisted in JetStream):
    workspaces.member.invited       → persist Notification row
    workspaces.member.joined        → notify inviter + other active members
    workspaces.member.role_changed  → notify the member whose role changed
    workspaces.member.removed       → notify the removed member
    workspaces.invitation.created   → email hook for unregistered invites (TODO)
    workspaces.created              → provisioning/analytics hook (TODO)
    audit.entry.created             → persist AuditLogEntry row
    apikeys.created                 → security/monitoring hook (TODO)
    apikeys.revoked                 → security/monitoring hook (TODO)
    jobs.execute                    → execute one scheduled-job run
    conversations.message.created   → persist notification pointers (bulk)
    agents.requests.chat            → ChatHandler on_request (wakes agent)

  Fanout (every replica receives the event, realtime push):
    notifications.created           → push to the user's WebSocket sessions
    conversations.message.live      → push thread update to participants
    conversations.renamed           → push title change to participants
    agents.run.event                → push token/tool events to watchers
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from src.core.security.crypto import SecretCipher
from src.db.session import SessionFactory
from src.events.bus import EventBus
from src.events.factory import WorkflowRegistry
from src.events.subjects import Subjects
from src.jobs.executor import execute_run
from src.models.workspace import WorkspaceMember
from src.realtime.manager import ConnectionManager
from src.services.audit import AuditService
from src.services.jobs import JobService
from src.services.notifications import NotificationService

logger = logging.getLogger(__name__)


async def _create_notification(
    session, bus: EventBus, *, correlation_id: str | None = None, **kwargs
) -> None:
    """Persist a notification and fan it out over the bus in one call."""
    service = NotificationService(session, bus)
    await service.create(**kwargs, correlation_id=correlation_id)


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
        changed_by = payload.get("changed_by_name", "A member")
        async with SessionFactory() as session:
            await _create_notification(
                session,
                bus,
                user_id=user_id,
                workspace_id=workspace_id,
                type="member_role_changed",
                title=f"Your role changed in {workspace_name}",
                body=(
                    f"{changed_by} changed your role from {payload.get('from_role')} "
                    f"to {payload.get('to_role')}."
                ),
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
        """Hook for inviting users who do not have an account yet.

        TODO(events): email delivery for invitations is not implemented yet.
        When it is, send an invite link to `payload["email"]` (build the URL
        from the invitation token + FRONTEND_URL) for unregistered recipients.
        Registered recipients are handled in-app via workspaces.member.invited.
        """
        if not payload.get("is_registered"):
            logger.info(
                "TODO(email): send invitation to %s for workspace %s (not implemented)",
                payload.get("email"),
                payload.get("workspace_id"),
            )

    async def on_workspace_created(payload: dict, metadata) -> None:
        """Provision workspace-scoped scheduled jobs for the new workspace.

        TODO(events): other provisioning/analytics hooks can live here too.
        """
        workspace_id = payload.get("workspace_id")
        if not workspace_id:
            return
        async with SessionFactory() as session:
            await JobService(session, bus, cipher).sync_definitions(
                workspace_ids=[workspace_id]
            )
        logger.info("workspace.created: %s (%s) by %s",
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
        if participant_ids is None:
            conversation_id = payload.get("conversation_id")
            workspace_id = payload.get("workspace_id")
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
        await execute_run(run_id)

    async def on_agent_profile_changed(payload: dict, metadata) -> None:
        workspace_id = payload.get("workspace_id")
        if not workspace_id:
            return
        async with SessionFactory() as session:
            result = await session.execute(
                select(WorkspaceMember.user_id).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.status == "active",
                )
            )
            user_ids = [r[0] for r in result.all()]
        if not user_ids:
            return
        await connection_manager.push_many(user_ids, payload, event="agents.profile.changed")

    async def _route_to_agents(payload: dict, metadata) -> None:
        """Durable side-effect of `conversations.message.created`: fan out to `agents.requests.chat`.

        Loop prevention: agent messages (sender_type == "agent") never route — otherwise
        an agent reply would re-wake every agent including itself.
        """
        if payload.get("sender_type") == "agent":
            return
        conversation_id = payload.get("conversation_id")
        workspace_id = payload.get("workspace_id")
        message_id = payload.get("message_id")
        sender_id = payload.get("sender_id")
        if not conversation_id or not workspace_id or not message_id:
            return
        async with SessionFactory() as session:
            from src.models.agent import Agent  # local import to avoid cycle
            from src.models.conversation import ConversationParticipant

            result = await session.execute(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == conversation_id,
                    ConversationParticipant.participant_type == "agent",
                )
            )
            agent_participants = list(result.scalars().all())
            if not agent_participants:
                return
            agent_ids = [p.participant_id for p in agent_participants]
            active_result = await session.execute(
                select(Agent.id).where(Agent.id.in_(agent_ids), Agent.is_active.is_(True))
            )
            active_ids = {r[0] for r in active_result.all()}
            for p in agent_participants:
                if p.participant_id not in active_ids:
                    continue
                from src.events.publisher import publish_event as _publish

                await _publish(
                    bus,
                    Subjects.AGENTS_REQUEST_CHAT,
                    {
                        "entity_type": "chat",
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "agent_id": p.participant_id,
                        "workspace_id": workspace_id,
                        "triggering_user_id": sender_id,
                    },
                )
            logger.debug("routed message %s to %d agent(s) in %s", message_id, len(active_ids), conversation_id)

    _orig_on_conversation_message = on_conversation_message

    async def on_conversation_message_with_routing(payload: dict, metadata) -> None:
        await _orig_on_conversation_message(payload, metadata)
        try:
            await _route_to_agents(payload, metadata)
        except Exception:
            logger.exception("agent routing failed for message %s", payload.get("message_id"))

    async def on_agents_request_chat(payload: dict, metadata) -> None:
        """Durable consumer: dispatch to ChatHandler.

        Decoupled from the routing durable consumer so backpressure on one
        agent run never blocks notification persistence.
        """
        try:
            from src.agents.handlers.base import AgentRequest
            from src.agents.handlers.chat import ChatHandler
            from src.secrets.factory import build_secret_store

            req = AgentRequest(
                entity_type=payload.get("entity_type", "chat"),
                conversation_id=payload["conversation_id"],
                message_id=payload["message_id"],
                agent_id=payload["agent_id"],
                workspace_id=payload["workspace_id"],
                triggering_user_id=payload.get("triggering_user_id") or payload.get("sender_id") or "",
            )
            handler = ChatHandler(bus=bus, secret_store=build_secret_store())
            await handler.on_request(req)
        except KeyError as exc:
            logger.warning("agents.requests.chat missing key %s: %s", exc, payload)
        except Exception:
            logger.exception("agents.requests.chat handler failed for %s", payload)

    async def on_agents_run_event(payload: dict, metadata) -> None:
        """Fanout: push agent run events to watching users (every replica)."""
        workspace_id = payload.get("workspace_id")
        conversation_id = payload.get("conversation_id")
        participant_ids: list[str] | None = payload.get("participant_user_ids") or payload.get("user_ids")
        if participant_ids is None and conversation_id:
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
            if not workspace_id:
                return
            async with SessionFactory() as session:
                result = await session.execute(
                    select(WorkspaceMember.user_id).where(
                        WorkspaceMember.workspace_id == workspace_id,
                        WorkspaceMember.status == "active",
                    )
                )
                participant_ids = [r[0] for r in result.all()]
        if not participant_ids:
            return
        await connection_manager.push_many(participant_ids, payload, event="agents.run.event")

    registry.register(Subjects.WORKSPACE_MEMBER_INVITED, on_member_invited)
    registry.register(Subjects.WORKSPACE_MEMBER_JOINED, on_member_joined)
    registry.register(Subjects.WORKSPACE_MEMBER_ROLE_CHANGED, on_member_role_changed)
    registry.register(Subjects.WORKSPACE_MEMBER_REMOVED, on_member_removed)
    registry.register(Subjects.WORKSPACE_INVITATION_CREATED, on_invitation_created)
    registry.register(Subjects.WORKSPACE_CREATED, on_workspace_created)
    registry.register(Subjects.AUDIT_ENTRY_CREATED, on_audit_entry)
    registry.register(Subjects.APIKEY_CREATED, on_apikey_created)
    registry.register(Subjects.APIKEY_REVOKED, on_apikey_revoked)
    registry.register(Subjects.JOBS_EXECUTE, on_job_execute)
    registry.register(Subjects.NOTIFICATIONS_CREATED, on_notification_created, fanout=True)
    registry.register(Subjects.CONVERSATION_MESSAGE_CREATED, on_conversation_message_with_routing)
    registry.register(Subjects.CONVERSATION_MESSAGE_LIVE, on_conversation_message_live, fanout=True)
    registry.register(Subjects.CONVERSATION_RENAMED, on_conversation_renamed, fanout=True)
    registry.register(Subjects.AGENT_PROFILE_CHANGED, on_agent_profile_changed, fanout=True)
    registry.register(Subjects.AGENTS_REQUEST_CHAT, on_agents_request_chat)
    registry.register(Subjects.AGENTS_RUN_EVENT, on_agents_run_event, fanout=True)
