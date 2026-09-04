from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID


class AgentUsage(Base):
    """One row per agent run (written by the chat handler's post_process)."""

    __tablename__ = "agent_usage"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(StringUUID(), nullable=False)
    agent_id: Mapped[str] = mapped_column(StringUUID(), nullable=False)
    user_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True)
    message_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_cents: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=Decimal("0")
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_agent_usage_workspace_created", "workspace_id", "created_at"),
        Index("ix_agent_usage_agent_created", "agent_id", "created_at"),
        Index("ix_agent_usage_user", "user_id"),
        Index("ix_agent_usage_status", "status"),
    )