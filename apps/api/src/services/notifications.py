from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import EventBus
from src.events.publisher import publish_audit
from src.events.subjects import Subjects
from src.models.core import Notification
from src.services.serializers import notification_to_dict

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, session: AsyncSession, bus: EventBus | None = None) -> None:
        self._session = session
        self._bus = bus

    async def create(
        self,
        *,
        user_id: str,
        workspace_id: str,
        type: str,
        title: str,
        body: str | None = None,
        metadata: dict | None = None,
        correlation_id: str | None = None,
    ) -> Notification:
        if not workspace_id:
            raise ValueError("notifications require a workspace_id")
        n = Notification(
            user_id=user_id,
            workspace_id=workspace_id,
            type=type,
            title=title,
            body=body,
            payload=metadata or {},
        )
        self._session.add(n)
        await self._session.commit()
        if self._bus is not None:
            # Transient: realtime fan-out to live sessions. No durable
            # consumer exists and nothing needs these replayed, so the NATS
            # backend publishes over core NATS (no JetStream persistence).
            await self._bus.publish(
                Subjects.NOTIFICATIONS_CREATED,
                notification_to_dict(n),
                correlation_id=correlation_id,
                transient=True,
            )
        return n

    async def list_for_user(
        self,
        user_id: str,
        *,
        acknowledged: bool | None = None,
        workspace_id: str | None = None,
    ) -> list[Notification]:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if workspace_id is not None:
            stmt = stmt.where(Notification.workspace_id == workspace_id)
        if acknowledged is not None:
            if acknowledged:
                stmt = stmt.where(Notification.acknowledged_at.is_not(None))
            else:
                stmt = stmt.where(Notification.acknowledged_at.is_(None))
        stmt = stmt.order_by(Notification.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def acknowledge(
        self,
        user_id: str,
        notification_id: str,
        *,
        workspace_id: str | None = None,
        ip_address: str | None = None,
    ) -> Notification | None:
        n = await self._get_for_user(user_id, notification_id, workspace_id)
        if n is None:
            return None
        n.acknowledged_at = datetime.now(UTC)
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=n.workspace_id,
            resource_type="notification",
            resource_id=n.id,
            action="notification.acknowledged",
            actor_user_id=user_id,
            ip_address=ip_address,
        )
        return n

    async def unacknowledge(
        self,
        user_id: str,
        notification_id: str,
        *,
        workspace_id: str | None = None,
        ip_address: str | None = None,
    ) -> Notification | None:
        n = await self._get_for_user(user_id, notification_id, workspace_id)
        if n is None:
            return None
        n.acknowledged_at = None
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=n.workspace_id,
            resource_type="notification",
            resource_id=n.id,
            action="notification.unacknowledged",
            actor_user_id=user_id,
            ip_address=ip_address,
        )
        return n

    async def _get_for_user(
        self,
        user_id: str,
        notification_id: str,
        workspace_id: str | None = None,
    ) -> Notification | None:
        stmt = select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
        if workspace_id is not None:
            stmt = stmt.where(Notification.workspace_id == workspace_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
