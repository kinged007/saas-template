from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, TypedDict

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import SOURCE_EVENT_KEY, EventBus
from src.events.publisher import publish_audit
from src.events.subjects import Subjects
from src.models.core import Notification, NotificationPreference
from src.services.serializers import notification_to_dict

logger = logging.getLogger(__name__)


DIGEST_TYPE = "*"
DIGEST_EXCLUDED_TYPES = ("conversation_message",)
CHANNELS = ("in-app", "email", "off")
DEFAULT_CHANNEL = "in-app"
# Preferences may only be written for a type the notification workflows emit,
# so nobody can fill a member's table with rows nothing ever reads.
KNOWN_TYPES = (
    "workspace_invitation",
    "member_joined",
    "member_role_changed",
    "member_removed",
    *DIGEST_EXCLUDED_TYPES,
)


def unsubscribe_url_for(token: str, type: str, frontend_url: str) -> str:
    base = (frontend_url or "").rstrip("/")
    return f"{base}/api/v1/notifications/unsubscribe?token={token}&type={type}"


def preferences_response(prefs) -> dict:
    """Wire shape for `GET|PUT /preferences` and its target-scoped twin, so both
    routes answer identically. It lives here because it needs `DIGEST_TYPE`, and
    `services.serializers` already imports this module."""
    return {
        "channels": {p.type: p.channel for p in prefs if p.type != DIGEST_TYPE},
        "digest_enabled": next((p.digest_enabled for p in prefs if p.type == DIGEST_TYPE), False),
    }


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
        source_event_id: str | None = None,
    ) -> Notification:
        """Persist one notification and fan it out.

        `source_event_id` makes the insert idempotent: the bus is at-least-once,
        so a redelivered event returns the notification the first delivery
        created instead of a second row for the same recipient. The key is
        reserved — `metadata[source_event_id]` is overwritten when it is set.
        """
        if not workspace_id:
            raise ValueError("notifications require a workspace_id")
        spec: NotificationSpec = {
            "user_id": user_id,
            "workspace_id": workspace_id,
            "type": type,
            "title": title,
            "body": body,
            "metadata": metadata,
        }
        if source_event_id and (
            existing := await self._find_by_source_event([spec], source_event_id)
        ):
            return existing[0]
        n = Notification(
            user_id=user_id,
            workspace_id=workspace_id,
            type=type,
            title=title,
            body=body,
            payload=self._payload(metadata, source_event_id),
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
        source_event_id: str | None = None,
    ) -> list[Notification]:
        """Persist many notifications in a single transaction and fan them out.

        All rows share one commit; the realtime publishes are issued
        concurrently after it, so callers never pay per-notification
        round-trips. Used by the conversation-message workflow, where a group
        conversation would otherwise mean one transaction per participant.
        `source_event_id` drops the recipients this event already notified
        (see `create`).

        Returns the rows it created, so the count is below `len(specs)`
        whenever a recipient was already notified; the drop is logged here
        rather than reported through the return value, the way
        `AuditService.record` reports a suppressed audit entry.
        """
        pending = list(specs)
        for spec in pending:
            if not spec["workspace_id"]:
                raise ValueError("notifications require a workspace_id")
        if source_event_id:
            already = {
                (n.user_id, n.workspace_id, n.type)
                for n in await self._find_by_source_event(pending, source_event_id)
            }
            pending = [
                s for s in pending if (s["user_id"], s["workspace_id"], s["type"]) not in already
            ]
            if len(pending) != len(specs):
                logger.info(
                    "notification fan-out for source event %s dropped %d of %d "
                    "already-notified recipients (correlation %s)",
                    source_event_id,
                    len(specs) - len(pending),
                    len(specs),
                    correlation_id or "-",
                )
        rows: list[Notification] = []
        for spec in pending:
            rows.append(
                Notification(
                    user_id=spec["user_id"],
                    workspace_id=spec["workspace_id"],
                    type=spec["type"],
                    title=spec["title"],
                    body=spec.get("body"),
                    payload=self._payload(spec.get("metadata"), source_event_id),
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
        workspace_id: str,
        acknowledged: bool | None = None,
    ) -> list[Notification]:
        """Notifications for one user in one workspace, newest first.

        `workspace_id` is required so the scope cannot be widened by
        omitting it, the same way `ApiKeyService` re-applies its owner
        predicate instead of trusting the caller.
        """
        stmt = select(Notification).where(
            Notification.user_id == user_id,
            Notification.workspace_id == workspace_id,
        )
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

    async def acknowledge_all(
        self,
        user_id: str,
        *,
        workspace_id: str,
        ip_address: str | None = None,
    ) -> int:
        """Acknowledge all unread notifications in one UPDATE, excluding
        conversation_message pointers (surfaced via conversation unread counts).
        Returns the number acknowledged."""
        result = await self._session.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.workspace_id == workspace_id,
                Notification.acknowledged_at.is_(None),
                Notification.type != "conversation_message",
            )
            .values(acknowledged_at=datetime.now(UTC))
        )
        count = int(result.rowcount or 0)
        if count:
            await self._session.commit()
            await publish_audit(
                self._bus,
                workspace_id=workspace_id,
                resource_type="notification",
                # The bulk scope, not a sentinel string: resource_id must stay
                # a UUID — Postgres binds it as one and a non-UUID value fails
                # the write before any SQL runs.
                resource_id=workspace_id,
                action="notifications.acknowledged",
                actor_user_id=user_id,
                details={"count": count},
                ip_address=ip_address,
            )
        return count

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

    async def get_preferences(self, user_id: str) -> list[NotificationPreference]:
        result = await self._session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
        return list(result.scalars().all())

    async def resolve_channel(self, user_id: str, type: str) -> str:
        """Channel for (user, type); missing row means `in-app`."""
        result = await self._session.execute(
            select(NotificationPreference.channel).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.type == type,
            )
        )
        return result.scalar_one_or_none() or DEFAULT_CHANNEL

    async def upsert_channels(
        self, user_id: str, channels: dict[str, str]
    ) -> list[NotificationPreference]:
        """Bulk upsert of per-type channels; generates tokens on email opt-in.
        Raises ValueError on an unknown type or channel."""
        rows: list[NotificationPreference] = []
        for type, channel in channels.items():
            if type not in KNOWN_TYPES:
                raise ValueError(f"unknown type {type!r}")
            if channel not in CHANNELS:
                raise ValueError(f"invalid channel {channel!r}")
            result = await self._session.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == user_id,
                    NotificationPreference.type == type,
                )
            )
            pref = result.scalar_one_or_none()
            if pref is None:
                pref = NotificationPreference(user_id=user_id, type=type, channel=channel)
                self._session.add(pref)
            else:
                pref.channel = channel
            if channel == "email":
                pref.ensure_token()
            rows.append(pref)
        await self._session.commit()
        return rows

    async def set_digest(self, user_id: str, enabled: bool) -> NotificationPreference:
        """Get-or-create the sentinel digest row and flip its flag."""
        result = await self._session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.type == DIGEST_TYPE,
            )
        )
        pref = result.scalar_one_or_none()
        if pref is None:
            pref = NotificationPreference(user_id=user_id, type=DIGEST_TYPE)
            self._session.add(pref)
        pref.digest_enabled = enabled
        await self._session.commit()
        return pref

    async def digest_enabled(self, user_id: str) -> bool:
        result = await self._session.execute(
            select(NotificationPreference.digest_enabled).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.type == DIGEST_TYPE,
            )
        )
        return bool(result.scalar_one_or_none())

    async def token_for(self, user_id: str, type: str) -> str | None:
        """Unsubscribe token for (user, type), generating it lazily."""
        result = await self._session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.type == type,
            )
        )
        pref = result.scalar_one_or_none()
        if pref is None:
            pref = NotificationPreference(user_id=user_id, type=type)
            self._session.add(pref)
        token = pref.ensure_token()
        await self._session.commit()
        return token

    async def unsubscribe(self, token: str, type: str) -> bool:  # noqa: A002 (shadows builtin, matches domain)
        """Flip email rows for the token owner to `in-app` (no auth).

        Any valid per-row token of a user authorizes that user's rows: the
        token proves ownership of the recipient mailbox. `all` flips every
        email row and clears the digest flag; otherwise only that type.
        Returns False when the token matches nothing (caller → 404).
        """
        result = await self._session.execute(
            select(NotificationPreference).where(NotificationPreference.unsubscribe_token == token)
        )
        anchor = result.scalars().first()
        if anchor is None:
            return False
        owner = anchor.user_id
        stmt = (
            select(NotificationPreference)
            .where(NotificationPreference.user_id == owner)
            .where(
                NotificationPreference.channel == "email"
                if type == "all"
                else (NotificationPreference.type == type)
            )
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        for pref in rows:
            pref.channel = DEFAULT_CHANNEL
        if type == "all":
            digest = (
                await self._session.execute(
                    select(NotificationPreference).where(
                        NotificationPreference.user_id == owner,
                        NotificationPreference.type == DIGEST_TYPE,
                    )
                )
            ).scalar_one_or_none()
            if digest is not None:
                digest.digest_enabled = False
        await self._session.commit()
        return True

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

    @staticmethod
    def _payload(metadata: dict | None, source_event_id: str | None) -> dict:
        payload = dict(metadata or {})
        if source_event_id:
            payload[SOURCE_EVENT_KEY] = source_event_id
        return payload

    async def _find_by_source_event(
        self, specs: Sequence[NotificationSpec], source_event_id: str
    ) -> list[Notification]:
        """Rows this source event already created for the given (user, workspace, type)."""
        keys = {(s["user_id"], s["workspace_id"], s["type"]) for s in specs}
        if not keys:
            return []
        user_ids, workspace_ids, types = zip(*keys, strict=True)
        # One predicate, then match the exact triples in Python: an OR of
        # per-spec ANDs grows with the recipient count and hits SQLite's
        # expression depth limit on a large conversation fan-out.
        result = await self._session.execute(
            select(Notification).where(
                Notification.payload[SOURCE_EVENT_KEY].as_string() == source_event_id,
                Notification.user_id.in_(user_ids),
                Notification.workspace_id.in_(workspace_ids),
                Notification.type.in_(types),
            )
        )
        return [n for n in result.scalars() if (n.user_id, n.workspace_id, n.type) in keys]
