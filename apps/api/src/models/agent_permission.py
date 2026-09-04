from __future__ import annotations

import uuid

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin


class AgentPermissionRequest(Base, TimestampMixin):
    """Paused run waiting on a human decision (approval gate).

    One row per `requires_approval` tool call. The run's `DeferredToolRequests`
    carries the tool_call_id; this row is the durable counterpart.
    TTL expiry → status=expired; denial → tool returns denial to model on resume.
    """

    __tablename__ = "agent_permission_requests"

    id: Mapped[str] = mapped_column(StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    agent_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    triggering_user_id: Mapped[str] = mapped_column(StringUUID(), nullable=False)
    run_message_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(100), nullable=False)
    args_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
