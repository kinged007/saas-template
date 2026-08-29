from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Sequence, TypedDict

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import EventBus
from src.events.publisher import publish_audit
from src.events.subjects import Subjects
from src.models.core import Notification
from src.services.serializers import notification_to_dict

logger = logging.getLogger(__name__)


class NotificationSpec(TypedDict):
    """Input for a notification to persist via `create_many`."""

    user_id: str
    workspace_id: str
    type: str
    title: str
    body: str | None
    metadata: dict[str, Any] | None


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

    async def create_many(
        self,
        specs: Sequence[NotificationSpec],
        *,
        correlation_id: str | None = None,
    ) -> list[Notification]:
        """Persist many notifications in a single transaction and fan them out.

        All rows share one commit; the realtime publishes are issued
        concurrently after it, so callers never pay per-notification
        round-trips. Used by the conversation-message workflow, where a group
        conversation would otherwise mean one transaction per participant.
        """
        rows: list[Notification] = []
        for spec in specs:
            if not spec["workspace_id"]:
                raise ValueError("notifications require a workspace_id")
            rows.append(
                Notification(
                    user_id=spec["user_id"],
                    workspace_id=spec["workspace_id"],
                    type=spec["type"],
                    title=spec["title"],
                    body=spec.get("body"),
                    payload=spec.get("metadata") or {},
                )
            )
        if not rows:
            return []
        self._session.add_all(rows)
        await self._session.commit()
        if self._bus is not None:
            # Transient: realtime fan-out to live sessions (see `create`).
            await asyncio.gather(
                *(
                    self._bus.publish(
                        Subjects.NOTIFICATIONS_CREATED,
                        notification_to_dict(n),
                        correlation_id=correlation_id,
                        transient=True,
                    )
                    for n in rows
                )
            )
        return rows

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

    async def acknowledge_for_conversation(
        self,
        user_id: str,
        workspace_id: str,
        conversation_id: str,
    ) -> int:
        """Acknowledge all unread conversation_message notifications for a
        conversation in one UPDATE, with a single aggregated audit event."""
        stmt = select(Notification.id, Notification.payload).where(
            Notification.user_id == user_id,
            Notification.workspace_id == workspace_id,
            Notification.type == "conversation_message",
            Notification.acknowledged_at.is_(None),
        )
        result = await self._session.execute(stmt)
        ids = [
            notification_id
            for notification_id, payload in result.all()
            if (payload or {}).get("conversation_id") == conversation_id
        ]
        if not ids:
            return 0
        await self._session.execute(
            update(Notification)
            .where(Notification.id.in_(ids))
            .values(acknowledged_at=datetime.now(UTC))
        )
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="conversation",
            resource_id=conversation_id,
            action="notifications.acknowledged",
            actor_user_id=user_id,
            details={"count": len(ids)},
        )
        return len(ids)

    async def unread_count(self, user_id: str, *, workspace_id: str) -> int:
        """Count unread notifications, excluding conversation_message pointers
        (they are surfaced through the conversation unread counts instead)."""
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.workspace_id == workspace_id,
                Notification.acknowledged_at.is_(None),
                Notification.type != "conversation_message",
            )
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

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
