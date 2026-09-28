from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin


class OAuthAccount(Base, TimestampMixin):
    """SSO identity link: one row per (provider, subject) pair.

    Identity survives email changes (subject is stable); email is only the
    first-connect fallback key. Multiple providers with the same email link
    to the same user.

    One-to-many per (user_id, provider) is the intended cardinality, not an
    oversight: uq_oauth_provider_subject is the only link key, so
    AuthService.upsert_oauth_user adds a subject instead of replacing the one
    already linked. A user legitimately holds several subjects under one
    provider when a shared IdP issues a separate subject per work email.
    """

    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_oauth_provider_subject"),)

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        StringUUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str] = mapped_column(String(320), nullable=False)
