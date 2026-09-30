from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dates import ensure_utc, now_utc
from src.core.permissions import ALL_PERMISSIONS_INCLUDING_KEY_ONLY, KEY_ONLY_PERMISSIONS
from src.events.bus import EventBus
from src.events.publisher import publish_audit, publish_event
from src.events.subjects import Subjects
from src.models.api_key import ApiKey
from src.models.workspace import User
from src.services.workspaces import WorkspaceService


class ApiKeyError(Exception):
    pass


class ApiKeyForbidden(ApiKeyError):
    """The caller lacks the permissions they tried to grant to a key."""


class ApiKeyNotFound(ApiKeyError):
    pass


def _payload_iso(value: datetime | None) -> str | None:
    """Serialize an ORM datetime for a publish payload.

    Normalized at the emission edge instead of read off the attribute: SQLite
    hands `DateTime(timezone=True)` back without an offset, and a consumer's
    `new Date(...)` reads a naive ISO string as local time.
    """
    return ensure_utc(value).isoformat() if value is not None else None


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
        membership = await WorkspaceService(self._session).get_membership(
            workspace_id, actor.id, active_only=True
        )
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

        if usage_quota is not None and usage_quota < 0:
            raise ApiKeyError("usage quota cannot be negative")
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
                "expires_at": _payload_iso(key.expires_at),
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

    def owner_scope(self, workspace_id: str, created_by_user_id: str) -> Select[tuple[ApiKey]]:
        """Base statement restricted to one user's keys in one workspace.

        The personal-scope predicate lives here (not in the route) so every
        key read shares one owner. Callers apply their own filters, counting
        and pagination on top — the scope can only ever narrow."""
        return select(ApiKey).where(
            ApiKey.workspace_id == workspace_id,
            ApiKey.created_by_user_id == created_by_user_id,
        )

    async def count_for_user(self, stmt: Select[tuple[ApiKey]]) -> int:
        """Rows the scoped statement matches, ignoring its ORDER BY."""
        count = await self._session.execute(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        return count.scalar_one()

    async def list_for_user(self, stmt: Select[tuple[ApiKey]]) -> list[ApiKey]:
        """Run an owner-scoped statement and return the page."""
        result = await self._session.execute(stmt)
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
        """
        stmt = select(ApiKey).where(ApiKey.key_hash == self._hash(raw))
        result = await self._session.execute(stmt)
        key = result.scalar_one_or_none()
        if key is None or key.revoked_at is not None:
            return None
        if key.expires_at is not None and ensure_utc(key.expires_at) <= now_utc():
            return None
        return key

    async def touch(self, key: ApiKey) -> bool:
        # ponytail: lifetime counter, never reset (usage_quota is a lifetime
        # cap); add a window start column + rollover here when true monthly
        # quotas are needed.
        """Record a successful use: bump the usage counter + last_used_at.

        Returns False and leaves the row alone when the quota is already
        spent. The counter bump and the quota test are one conditional
        UPDATE, so two requests that read usage_count before either writes
        race on this statement alone and only the first can spend the last
        unit. `refresh` keeps the caller's key in step with the row (the
        session does not expire on commit), so quota headers read
        post-increment values and a later flush cannot write the old count
        back."""
        result = await self._session.execute(
            update(ApiKey)
            .where(
                ApiKey.id == key.id,
                or_(ApiKey.usage_quota.is_(None), ApiKey.usage_count < ApiKey.usage_quota),
            )
            .values(usage_count=ApiKey.usage_count + 1, last_used_at=now_utc())
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            return False
        await self._session.commit()
        await self._session.refresh(key)
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
        if usage_quota is not None and usage_quota < 0:
            raise ApiKeyError("usage quota cannot be negative")
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
