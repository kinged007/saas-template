from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import EventBus
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
            await self._bus.publish(Subjects.NOTIFICATIONS_CREATED, notification_to_dict(n))
        return n

    async def list_for_user(
        self, user_id: str, *, acknowledged: bool | None = None
    ) -> list[Notification]:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if acknowledged is not None:
            if acknowledged:
                stmt = stmt.where(Notification.acknowledged_at.is_not(None))
            else:
                stmt = stmt.where(Notification.acknowledged_at.is_(None))
        stmt = stmt.order_by(Notification.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def acknowledge(self, user_id: str, notification_id: str) -> Notification | None:
        stmt = select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
        result = await self._session.execute(stmt)
        n = result.scalar_one_or_none()
        if n is None:
            return None
        n.acknowledged_at = datetime.now(UTC)
        await self._session.commit()
        return n

    async def unacknowledge(self, user_id: str, notification_id: str) -> Notification | None:
        stmt = select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
        result = await self._session.execute(stmt)
        n = result.scalar_one_or_none()
        if n is None:
            return None
        n.acknowledged_at = None
        await self._session.commit()
        return n
