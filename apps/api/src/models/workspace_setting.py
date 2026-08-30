from __future__ import annotations

import uuid

from typing import Any

from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin


class WorkspaceSetting(Base, TimestampMixin):
    __tablename__ = "workspace_settings"
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_workspace_settings_workspace_key"),
    )

    id: Mapped[str] = mapped_column(StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    updated_by_user_id: Mapped[str | None] = mapped_column(StringUUID(), index=True, nullable=True)
