from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StrEnum, StringUUID, TimestampMixin

# Why a refresh token row died. Only "rotated" means "was exchanged, so a later
# presentation of it is a replay" — the reuse signal keys off it. Shared by every
# writer, and spelled out again in the ck_refresh_tokens_revoke_reason check
# constraint below: no type checker runs on this package, so the database is what
# rejects a reason outside this set.
RevokeReason = Literal["rotated", "user", "logout", "password", "reuse"]


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Bootstrap superuser (SUPERADMIN_EMAIL). Global jobs and other
    # deployment-wide administration are gated on this flag.
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_verified_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# ponytail: historical drift — merged PRs changed model-only widths
# (RefreshToken.token_hash 64→255, User.password_hash 128→255,
# StoredSecret.secret_key 400→500 to match the migrated schema) without
# migrations, and new unique/index flags render as phantom diffs. 0013
# converges the constraint/column drift; the VARCHAR widenings are
# live-compatible (narrow→wide, in-row) and intentionally left unmigrated.
# Type changes ship only via explicit migration + human review (env.py
# keeps compare_type off), so a future narrowing needs its own migration
# with a data check first.


class AuthToken(Base, TimestampMixin):
    """Single-use opaque token for password-reset and email-verification flows.

    Raw value is never stored — only its SHA-256 (via OpaqueToken), same as
    refresh tokens. One table, `purpose` discriminates; `consumed_at` enforces
    single-use."""

    __tablename__ = "auth_tokens"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    # password_reset | email_verification
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RefreshToken(Base, TimestampMixin):
    __tablename__ = "refresh_tokens"

    # Same constraint 0020 creates; kept on the model so `create_all` (tests,
    # fresh installs) and the ORM agree on the domain. The naming convention
    # (src/db/base.py) prefixes ck_<table>_ onto the declared name, so the bare
    # suffix lands ck_refresh_tokens_revoke_reason — declaring the full name
    # would double it (docs/MIGRATIONS.md, Dialect branches).
    __table_args__ = (
        CheckConstraint(
            "revoke_reason IS NULL OR revoke_reason IN "
            "('rotated', 'user', 'logout', 'password', 'reuse')",
            name="revoke_reason",
        ),
    )

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[RevokeReason | None] = mapped_column(String(20), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    # Members without TOTP enrolled are refused workspace access while true.
    # The global MFA_REQUIRED setting overrides this per workspace: when the
    # setting is on, every workspace requires MFA regardless of this flag.
    mfa_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Workspace-level feature flags: {key: bool}. Absent key = default-on.
    # See docs/FEATURE_FLAGS.md for the registry.
    flags: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class Role(Base, TimestampMixin):
    """Workspace-scoped role. system roles are created per workspace on creation."""

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MemberStatus(StrEnum):
    """The domain `ck_workspace_members_status` below enforces.

    Copied off the constraint rather than enumerated, as `MemberStatus` in
    `apps/web/src/types.ts` is. The API writes `active` and `suspended`;
    `invited` has no writer and survives only as a pre-0017 value.
    """

    ACTIVE = "active"
    INVITED = "invited"
    SUSPENDED = "suspended"


# Whether a status reads as an active membership, decided per status so a
# status the domain gains later is refused at every read until it is stated
# here. Every `MemberStatus` has an entry; pinned by
# `test_active_membership_decides_every_member_status`.
#
# `active` is active at every read. `suspended` is active nowhere: no access,
# no listing, no co-member profile visibility, no `member_joined`
# notification, and it cannot leave on its own (a manager removes or
# reactivates it). `invited` is active nowhere too — it has no writer and
# survives only as a pre-0017 value, stated so a future invite-pending status
# cannot reuse the value silently.
READS_AS_ACTIVE: dict[str, bool] = {
    MemberStatus.ACTIVE.value: True,
    MemberStatus.INVITED.value: False,
    MemberStatus.SUSPENDED.value: False,
}
ACTIVE_MEMBERSHIP_STATUSES: tuple[str, ...] = tuple(
    status for status, active in READS_AS_ACTIVE.items() if active
)


class WorkspaceMember(Base, TimestampMixin):
    __tablename__ = "workspace_members"

    # Same constraint the 0017 migration creates; kept on the model so
    # `create_all` (tests, fresh installs) and the ORM agree on the domain.
    # Bare suffix for the same convention reason as RefreshToken above.
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'invited', 'suspended')",
            name="status",
        ),
    )

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    role_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )  # active | invited | suspended
