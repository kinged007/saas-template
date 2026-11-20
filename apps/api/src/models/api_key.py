from __future__ import annotations

import uuid

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin

# A quota below 1 is refused with these words both over HTTP (the schema
# validator) and by ApiKeyService (seed data, direct callers). It lives here so
# neither copy can drift.
QUOTA_MIN_MESSAGE = "usage quota must be at least 1 (omit it or send null for unlimited)"

# The largest quota the usage_quota column holds on both backends: sa.Integer
# is int32 on the default PostgreSQL and int64 on SQLite, so anything larger
# is refused with these words instead of overflowing into a silently
# unlimited key. ponytail: ceiling is the int32 column; upgrade path is a
# BigInteger column with le=2**63 - 1 (plus `make db-new m="..."`).
MAX_QUOTA = 2**31 - 1
QUOTA_MAX_MESSAGE = f"usage quota must be at most {MAX_QUOTA} (omit it or send null for unlimited)"
QUOTA_TYPE_MESSAGE = "usage quota must be an integer"


class ApiKey(Base, TimestampMixin):
    """Workspace-scoped API key. Only a hash of the secret is stored."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by_user_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    last_used_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Optional hard expiry. Auth rejects the key once it passes, and the
    # apikeys.cleanup job revokes it on the next pass. Indexed for the job's
    # scan and for the list view's expires_at sort.
    expires_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    revoked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # usage_quota caps usage_window_count, which counts the uses of the current
    # calendar month (UTC); usage_count stays the lifetime total.
    usage_window_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_window_start: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
