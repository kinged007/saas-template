"""Subscriber-side workflows: consume domain events and produce side effects.

Workflows open their own DB session per event (they may run in a separate
process in production), so they never depend on request-scoped dependencies.

The notification workflow is the reference implementation:
  workspaces.member.invited  (durable)  → persist Notification row
  notifications.created      (fanout)   → realtime push to WebSockets

The durable subscription runs once per deployment (JetStream queue group);
the fanout subscription runs in *every* replica so the WS push reaches the
user regardless of which replica holds their socket.
"""

from __future__ import annotations

import logging

from src.db.session import SessionFactory
from src.events.bus import EventBus
from src.events.factory import WorkflowRegistry
from src.events.subjects import Subjects
from src.realtime.manager import ConnectionManager
from src.services.notifications import NotificationService

logger = logging.getLogger(__name__)


def build_workflows(
    registry: WorkflowRegistry,
    bus: EventBus,
    connection_manager: ConnectionManager,
) -> None:
    async def on_member_invited(payload: dict, metadata) -> None:
        user_id = payload.get("user_id")
        if not user_id:
            return
        async with SessionFactory() as session:
            service = NotificationService(session, bus)
            notification = await service.create(
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
            )
        logger.info("notification persisted for user %s (%s)", user_id, notification.id)

    async def on_notification_created(payload: dict, metadata) -> None:
        """Realtime fan-out: push every new notification to live sessions."""
        user_id = payload.get("user_id")
        if not user_id:
            return
        await connection_manager.push(user_id=user_id, payload=payload)

    registry.register(Subjects.WORKSPACE_MEMBER_INVITED, on_member_invited)
    registry.register(Subjects.NOTIFICATIONS_CREATED, on_notification_created, fanout=True)
