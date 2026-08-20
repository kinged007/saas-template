"""Audit log model for tracking important actions."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin


class AuditLogEntry(Base, TimestampMixin):
    """Immutable audit trail entry.

    Rows are append-only: nothing in the application ever updates or deletes an
    audit entry, which keeps the trail trustworthy for compliance.
    """

    __tablename__ = "audit_log_entries"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Nullable: user-scoped actions (auth events, ...) have no workspace.
    workspace_id: Mapped[str | None] = mapped_column(StringUUID(), index=True, nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str] = mapped_column(StringUUID(), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
