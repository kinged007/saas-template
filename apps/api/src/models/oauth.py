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
    oversight: uq_oauth_provider_subject is the only link key, and
    AuthService.upsert_oauth_user looks an identity up by (provider, subject)
    alone, so it adds a subject rather than replacing the one already linked.
    The fan-out fires when a new subject resolves to an email that already
    belongs to a user: the IdP re-issued the subject for the same person, or
    the user changed their email. A separate subject per work email matches
    no existing user and creates a second user instead.

    The fallback links on the unverified email claim (normalize_identity never
    checks email_verified), so it is only as safe as the IdP: a provider that
    lets a caller assert an arbitrary email can attach a subject to another
    user's account.
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
