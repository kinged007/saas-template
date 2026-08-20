"""Immutable audit trail service.

Every meaningful action in the product is recorded here.
Rows are append-only: nothing in the application ever updates or deletes an
audit entry, which keeps the trail trustworthy for enterprise compliance.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    ) -> AuditLogEntry:
        """Append one audit entry and commit it immediately.

        Committed on its own so the record survives even if a later step of
        the calling transaction fails. `workspace_id` is optional: user-scoped
        actions (auth, ...) have no workspace.
        """
        entry = AuditLogEntry(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            details=details or {},
            ip_address=ip_address,
            created_at=created_at or datetime.now(UTC),
        )
        self._session.add(entry)
        await self._session.commit()
        return entry

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


def audit_log_to_dict(entry: AuditLogEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "workspace_id": entry.workspace_id,
        "actor_user_id": entry.actor_user_id,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "action": entry.action,
        "details": entry.details,
        "ip_address": entry.ip_address,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }
