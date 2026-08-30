from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(300), nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_allowlist: Mapped[list | None] = mapped_column(JSON, nullable=True)
    mcp_servers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    execution_target: Mapped[str | None] = mapped_column(String(30), nullable=True)
    role_id: Mapped[str | None] = mapped_column(StringUUID(), index=True, nullable=True)
    skills: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    custom_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[str | None] = mapped_column(StringUUID(), index=True, nullable=True)
    updated_by_user_id: Mapped[str | None] = mapped_column(StringUUID(), index=True, nullable=True)
