from __future__ import annotations

import hashlib
import operator
import secrets
from datetime import datetime

from sqlalchemy import Select, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dates import ensure_utc, iso_or_none, now_utc
from src.core.permissions import ALL_PERMISSIONS_INCLUDING_KEY_ONLY, KEY_ONLY_PERMISSIONS
from src.events.bus import EventBus
from src.events.publisher import publish_audit, publish_event
from src.events.subjects import Subjects
from src.models.api_key import (
    MAX_QUOTA,
    QUOTA_MAX_MESSAGE,
    QUOTA_MIN_MESSAGE,
    QUOTA_TYPE_MESSAGE,
    ApiKey,
)
from src.models.workspace import User
from src.services.workspaces import WorkspaceService


class ApiKeyError(Exception):
    pass


class ApiKeyForbidden(ApiKeyError):
    """The caller lacks the permissions they tried to grant to a key."""


class ApiKeyNotFound(ApiKeyError):
    pass


def _quota(usage_quota: int | None) -> int | None:
    """Strict-type then range-check a service-side quota.

    `operator.index` accepts anything int-like (int, bool, numpy ints) and
    refuses float/str values that only the schema would have coerced: a
    direct caller that passes 5.5 must not reach the Integer column through
    the range guards.
    """
    if usage_quota is None:
        return None
    try:
        quota = operator.index(usage_quota)
    except TypeError:
        raise ApiKeyError(QUOTA_TYPE_MESSAGE) from None
    if quota < 1:
        raise ApiKeyError(QUOTA_MIN_MESSAGE)
    if quota > MAX_QUOTA:
        raise ApiKeyError(QUOTA_MAX_MESSAGE)
    return quota


class ApiKeyService:
    """Workspace-scoped API key management.

    Keys are granted an explicit permission list (like a role) but can never
    exceed the creator's own permissions: the effective permission set of the
    creating user is always enforced server-side, so a user cannot mint a key
    that escalates beyond what they personally can do. When the creator is
    itself an API key, the cap is the intersection of the owner's role and the
    minting key's own permission list — a key can never grant a permission it
    does not hold itself.

    Keys are personal credentials: every read and write is scoped to the
    owning user (`created_by_user_id`). Even workspace admins see and manage
    only their own keys.
    """

    PREFIX = "sk_live_"

    def __init__(self, session: AsyncSession, bus: EventBus | None = None) -> None:
        self._session = session
        self._bus = bus

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _hash(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _prefix(raw: str) -> str:
        body = raw[len(ApiKeyService.PREFIX) : len(ApiKeyService.PREFIX) + 8]
        return f"{ApiKeyService.PREFIX}{body}"

    @classmethod
    def generate(cls) -> str:
        return f"{cls.PREFIX}{secrets.token_urlsafe(32)}"

    # ------------------------------------------------------------------- keys

    async def create_api_key(
        self,
        *,
        workspace_id: str,
        name: str,
        permissions: list[str],
        actor: User,
        ip_address: str | None = None,
        minting_key: ApiKey | None = None,
        usage_quota: int | None = None,
        expires_at: datetime | None = None,
    ) -> tuple[ApiKey, str]:
        """Create a key whose permissions are capped by the actor's own.

        When the request was authenticated with an API key, the cap is the
        intersection of the owner's role permissions and the minting key's
        own permission list. Returns (key, raw_secret); the raw secret is
        only ever returned once.
        """
        name = name.strip()
        membership = await WorkspaceService(self._session).get_membership(workspace_id, actor.id)
        if membership is None:
            raise ApiKeyForbidden("you are not a member of this workspace")
        _, role = membership

        requested = set(permissions)
        unknown = sorted(requested - set(ALL_PERMISSIONS_INCLUDING_KEY_ONLY) - {"*"})
        if unknown:
            raise ApiKeyError(f"unknown permissions: {', '.join(unknown)}")
        # Notification scopes are key-only: any member may hold them on a key
        # (notifications are personal); the role cap applies to the rest.
        capped = requested - set(KEY_ONLY_PERMISSIONS)
        allowed = set(role.permissions)
        if minting_key is not None and "*" not in minting_key.permissions:
            allowed &= set(minting_key.permissions)
        if "*" not in allowed and not capped <= allowed:
            denied = sorted(capped - allowed)
            raise ApiKeyForbidden(f"cannot grant permissions you do not have: {', '.join(denied)}")

        usage_quota = _quota(usage_quota)
        if expires_at is not None and ensure_utc(expires_at) <= now_utc():
            raise ApiKeyError("expiry must be in the future")

        raw = self.generate()
        key = ApiKey(
            workspace_id=workspace_id,
            name=name,
            key_prefix=self._prefix(raw),
            key_hash=self._hash(raw),
            permissions=sorted(requested),
            created_by_user_id=actor.id,
            usage_quota=usage_quota,
            # Normalize to UTC on write: SQLite's DateTime drops the offset and
            # stores the wall clock, which would shift the instant auth compares.
            expires_at=ensure_utc(expires_at) if expires_at is not None else None,
        )
        self._session.add(key)
        await self._session.commit()

        await publish_event(
            self._bus,
            Subjects.APIKEY_CREATED,
            {
                "apikey_id": key.id,
                "workspace_id": workspace_id,
                "name": key.name,
                "key_prefix": key.key_prefix,
                "permissions": key.permissions,
                "created_by_user_id": actor.id,
                "created_by_name": actor.display_name,
                "expires_at": iso_or_none(key.expires_at),
            },
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="apikey",
            resource_id=key.id,
            action="apikey.created",
            actor_user_id=actor.id,
            details={
                "name": key.name,
                "key_prefix": key.key_prefix,
                "permissions": key.permissions,
            },
            ip_address=ip_address,
        )
        return key, raw

    @staticmethod
    def _scope(
        workspace_id: str, created_by_user_id: str, stmt: Select[tuple[ApiKey]]
    ) -> Select[tuple[ApiKey]]:
        """AND the owner predicate onto `stmt`, so it can only narrow.

        Only `Select` is accepted: a subquery or compound select has no
        `.where`, so it raises here rather than executing unscoped. Do not
        wrap this call in try/except — a swallowed error would skip the scope.
        """
        return stmt.where(
            ApiKey.workspace_id == workspace_id,
            ApiKey.created_by_user_id == created_by_user_id,
        )

    async def count_for_user(
        self, workspace_id: str, created_by_user_id: str, stmt: Select[tuple[ApiKey]]
    ) -> int:
        """Rows the statement matches within one user's scope, ignoring its ORDER BY.

        The owner predicate is re-applied here, so a statement from another
        workspace or owner cannot widen the scope. ORDER BY, LIMIT and OFFSET
        are stripped: the count is the whole scope, not one page of it."""
        count = await self._session.execute(
            select(func.count()).select_from(
                self._scope(workspace_id, created_by_user_id, stmt)
                .order_by(None)
                .limit(None)
                .offset(None)
                .subquery()
            )
        )
        return count.scalar_one()

    async def list_for_user(
        self, workspace_id: str, created_by_user_id: str, stmt: Select[tuple[ApiKey]]
    ) -> list[ApiKey]:
        """Run the statement within one user's scope and return the page.

        The owner predicate is re-applied here, so a statement from another
        workspace or owner cannot widen the scope."""
        result = await self._session.execute(self._scope(workspace_id, created_by_user_id, stmt))
        return list(result.scalars().all())

    async def revoke_api_key(
        self,
        workspace_id: str,
        api_key_id: str,
        *,
        actor: User | None = None,
        ip_address: str | None = None,
    ) -> ApiKey:
        key = await self._session.get(ApiKey, api_key_id)
        if key is None or key.workspace_id != workspace_id:
            raise ApiKeyNotFound("api key not found")
        # Keys are personal: not even workspace admins may revoke another
        # user's key. 404 (not 403) so the id's existence is not leaked.
        if actor is not None and key.created_by_user_id != actor.id:
            raise ApiKeyNotFound("api key not found")
        if key.revoked_at is None:
            key.revoked_at = now_utc()
            await self._session.commit()
        await publish_event(
            self._bus,
            Subjects.APIKEY_REVOKED,
            {
                "apikey_id": key.id,
                "workspace_id": workspace_id,
                "name": key.name,
                "key_prefix": key.key_prefix,
                "revoked_by_user_id": actor.id if actor else None,
            },
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="apikey",
            resource_id=key.id,
            action="apikey.revoked",
            actor_user_id=actor.id if actor else None,
            details={"name": key.name, "key_prefix": key.key_prefix},
            ip_address=ip_address,
        )
        return key

    async def authenticate(self, raw: str) -> ApiKey | None:
        """Resolve a raw bearer secret to an active key, or None.

        A key past its `expires_at` is rejected here rather than relying on the
        cleanup job, so expiry takes effect the moment it passes.

        Takes the row lock for the rest of the transaction, so the quota
        charge runs inside the transaction that authenticated the key.
        """
        stmt = select(ApiKey).where(ApiKey.key_hash == self._hash(raw)).with_for_update()
        result = await self._session.execute(stmt)
        key = result.scalar_one_or_none()
        if key is None or key.revoked_at is not None:
            return None
        if key.expires_at is not None and ensure_utc(key.expires_at) <= now_utc():
            return None
        return key

    async def record_use(self, key: ApiKey, now: datetime | None = None) -> bool:
        """Count one successful use; False when the month's quota is spent.

        The rollover, the quota test and the increment are one UPDATE, so
        concurrent requests carrying one key cannot interleave a
        read-modify-write and consume more than `usage_quota` uses, and cannot
        write a stale `0` over each other's increment on SQLite (which ignores
        FOR UPDATE and serialises writers per statement instead).
        `authenticate` holds the row lock, which is what makes the budget exact
        on Postgres.

        The window is month-aligned in UTC rather than anchored to the first
        use: any request landing in a new calendar month opens a fresh window,
        so the stored start is the first instant of that month. Only a strictly
        earlier stored month rolls — the same month is current, and a later one
        means the host clock moved backwards, which would hand out a second full
        budget, so the counter is left alone and the key fails closed instead.
        `usage_count` is the lifetime total and is never reset.

        Returns False without committing, so the caller can report the
        untouched counters: a rejected request neither counts nor opens the
        next window. Those counters are the ones `authenticate` loaded, which
        is the committed value on a row-lock backend and at most one unit
        behind on SQLite, where a concurrent writer can slip in between.
        """
        now = ensure_utc(now or now_utc())
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rolled = or_(ApiKey.usage_window_start.is_(None), ApiKey.usage_window_start < month_start)
        windowed = case((rolled, 0), else_=ApiKey.usage_window_count)
        result = await self._session.execute(
            update(ApiKey)
            .where(
                ApiKey.id == key.id,
                or_(ApiKey.usage_quota.is_(None), windowed < ApiKey.usage_quota),
            )
            .values(
                usage_count=ApiKey.usage_count + 1,
                usage_window_count=windowed + 1,
                usage_window_start=case((rolled, month_start), else_=ApiKey.usage_window_start),
                last_used_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            return False
        # The rollover is a case() on the stored month, which the ORM cannot
        # evaluate in place, so the row is re-read instead: the quota headers
        # the caller reports must come from the values the database now holds.
        # ponytail: that costs a PK SELECT inside the lock authenticate already
        # holds. Ceiling: one extra read per key-authenticated request.
        # Upgrade path: UPDATE ... RETURNING.
        await self._session.refresh(key)
        await self._session.commit()
        return True

    async def set_quota(
        self,
        workspace_id: str,
        api_key_id: str,
        usage_quota: int | None,
        *,
        actor: User | None = None,
        ip_address: str | None = None,
    ) -> ApiKey:
        """Set (or clear with None) a key's quota.

        Personal scope, like revoke: only the key's owner may change its
        quota (404, not 403, so another user's key id is not leaked)."""
        key = await self._session.get(ApiKey, api_key_id)
        if key is None or key.workspace_id != workspace_id:
            raise ApiKeyNotFound("api key not found")
        if actor is not None and key.created_by_user_id != actor.id:
            raise ApiKeyNotFound("api key not found")
        usage_quota = _quota(usage_quota)
        key.usage_quota = usage_quota
        await self._session.commit()
        await publish_event(
            self._bus,
            Subjects.APIKEY_UPDATED,
            {
                "apikey_id": key.id,
                "workspace_id": workspace_id,
                "name": key.name,
                "key_prefix": key.key_prefix,
                "usage_quota": usage_quota,
                "updated_by_user_id": actor.id if actor else None,
            },
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="apikey",
            resource_id=key.id,
            action="apikey.updated",
            actor_user_id=actor.id if actor else None,
            details={
                "name": key.name,
                "key_prefix": key.key_prefix,
                "usage_quota": usage_quota,
            },
            ip_address=ip_address,
        )
        return key
