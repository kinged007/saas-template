from __future__ import annotations

import uuid

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin, Vector1536


class AgentMemory(Base, TimestampMixin):
    """A durable memory scoped to one (workspace, agent, user) triple."""

    __tablename__ = "agent_memories"
    __table_args__ = (
        Index("ix_agent_memories_triple", "workspace_id", "agent_profile_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(StringUUID(), nullable=False)
    agent_profile_id: Mapped[str] = mapped_column(StringUUID(), nullable=False)
    user_id: Mapped[str] = mapped_column(StringUUID(), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # fact | preference | summary
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(Vector1536(), nullable=True)