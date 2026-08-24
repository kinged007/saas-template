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

  Fanout (every replica receives the event, realtime push):
    notifications.created           → push to the user's WebSocket sessions

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

    async def on_job_execute(payload: dict, metadata) -> None:
        """Execute one scheduled-job run (durable, load-balanced consumer).

        The executor claims the run atomically before running it, so bus
        redeliveries or extra replicas never duplicate an execution.
        """
        run_id = payload.get("run_id")
        if not run_id:
            return
        await execute_run(run_id)

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
