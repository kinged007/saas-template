from __future__ import annotations

import secrets
import uuid

from sqlalchemy import JSON, Boolean, DateTime, String, UniqueConstraint
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
    )  # pending|accepted|declined|revoked|expired  (keep in step with `InvitationStatus`
    # in apps/web/src/types.ts; tests/test_invitation_status_vocabulary.py fails on drift)
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NotificationPreference(Base, TimestampMixin):
    """Per-user channel control for one notification type.

    One row per (user_id, type); missing row means channel `in-app`.
    The sentinel type `"*"` carries the global digest flag; its channel
    is unused. `unsubscribe_token` is a per-row opaque bearer generated
    lazily on first email opt-in (stdlib, revocable by regenerating).
    """

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "type", name="uq_notification_preferences_user_id_type"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # event type, or "*" for digest
    channel: Mapped[str] = mapped_column(
        String(10), default="in-app", nullable=False
    )  # in-app|email|off
    digest_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    unsubscribe_token: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    def ensure_token(self) -> str:
        if not self.unsubscribe_token:
            self.unsubscribe_token = secrets.token_urlsafe(32)
        return self.unsubscribe_token


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
