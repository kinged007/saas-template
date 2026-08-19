from __future__ import annotations

import uuid

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin


class Invitation(Base, TimestampMixin):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role_id: Mapped[str] = mapped_column(StringUUID(), nullable=False)
    invited_by_user_id: Mapped[str] = mapped_column(StringUUID(), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )  # pending|accepted|declined|revoked
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. workspace_invitation
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    acknowledged_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
