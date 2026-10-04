"""Immutable audit trail service.

Every meaningful action in the product is recorded here.
Rows are append-only: nothing in the application ever updates or deletes an
audit entry, which keeps the trail trustworthy for enterprise compliance.

The second invariant: at most one entry per source event. The bus is
at-least-once, so a redelivered event reaches the audit workflow again and
`record` returns the entry the first delivery already filed instead of adding
a second one. Two genuine failures are two publishes, i.e. two source events,
and both are recorded.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import SOURCE_EVENT_KEY
from src.models.audit import AuditLogEntry

logger = logging.getLogger(__name__)


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        workspace_id: str | None,
        resource_type: str,
        resource_id: str,
        action: str,
        actor_user_id: str | None = None,
        details: dict | None = None,
        ip_address: str | None = None,
        created_at: datetime | None = None,
        source_event_id: str | None = None,
    ) -> AuditLogEntry:
        """Append one audit entry and commit it immediately.

        Committed on its own so the record survives even if a later step of
        the calling transaction fails. `workspace_id` is optional: user-scoped
        actions (auth, ...) have no workspace.

        `source_event_id` is the bus event this entry was derived from, kept
        in `details`. If an entry for the same (workspace, resource, action,
        source event) exists it is returned unchanged and nothing is written.
        The key is reserved: a caller-supplied `details[source_event_id]` is
        overwritten, and the API shape strips it (see `public_details`).

        # ponytail: check-then-insert, so two deliveries of one envelope that
        # overlap can both miss and both write (one duplicate row). The window
        # is not simultaneity but redelivery: ACK_WAIT_SECONDS (30s) lets a
        # queue group hand a nacked or ack-timed-out message to another replica
        # while this handler is still running. The lookup filters on
        # `workspace_id` alone (the only indexed column) and runs on every
        # audit write, so it scans the workspace's audit history. The index
        # that fixes that cost is the one that closes the race above, so it is
        # a single migration to schedule.
        # Upgrade path: one migration adding a unique index over
        # (workspace_id, resource_type, resource_id, action, source_event_id).
        """
        if source_event_id:
            duplicate = await self._find_by_source_event(
                workspace_id, resource_type, resource_id, action, source_event_id
            )
            if duplicate is not None:
                logger.info(
                    "audit entry for source event %s already recorded (%s)",
                    source_event_id,
                    action,
                )
                return duplicate
        stored_details = dict(details or {})
        if source_event_id:
            stored_details[SOURCE_EVENT_KEY] = source_event_id
        entry = AuditLogEntry(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            details=stored_details,
            ip_address=ip_address,
            created_at=created_at or datetime.now(UTC),
        )
        self._session.add(entry)
        await self._session.commit()
        return entry

    async def _find_by_source_event(
        self,
        workspace_id: str | None,
        resource_type: str,
        resource_id: str,
        action: str,
        source_event_id: str,
    ) -> AuditLogEntry | None:
        result = await self._session.execute(
            select(AuditLogEntry)
            .where(
                AuditLogEntry.workspace_id == workspace_id,
                AuditLogEntry.resource_type == resource_type,
                AuditLogEntry.resource_id == resource_id,
                AuditLogEntry.action == action,
                AuditLogEntry.details[SOURCE_EVENT_KEY].as_string() == source_event_id,
            )
            .order_by(AuditLogEntry.created_at)
            .limit(1)
        )
        return result.scalars().first()

    async def list_for_resource(
        self,
        workspace_id: str,
        resource_type: str,
        resource_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AuditLogEntry]:
        stmt = (
            select(AuditLogEntry)
            .where(
                AuditLogEntry.workspace_id == workspace_id,
                AuditLogEntry.resource_type == resource_type,
                AuditLogEntry.resource_id == resource_id,
            )
            .order_by(desc(AuditLogEntry.created_at), desc(AuditLogEntry.id))
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


def public_details(details: dict | None) -> dict[str, Any]:
    """`details` without the internal `source_event_id` key.

    The key drives the dedupe and means nothing to a reader of the audit log,
    so it stays out of the API shape.
    """
    return {k: v for k, v in (details or {}).items() if k != SOURCE_EVENT_KEY}
