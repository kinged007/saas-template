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
    # Email the provider reported at connect time. Lets the "connected
    # accounts" list tell two same-provider logins apart; not an identity
    # key, so a change at the provider never re-keys the link.
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
