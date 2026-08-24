from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dates import now_utc
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
    ) -> tuple[ApiKey, str]:
        """Create a key whose permissions are capped by the actor's own.

        When the request was authenticated with an API key, the cap is the
        intersection of the owner's role permissions and the minting key's
        own permission list. Returns (key, raw_secret); the raw secret is
        only ever returned once.
        """
        membership = await WorkspaceService(self._session).get_membership(workspace_id, actor.id)
        if membership is None:
            raise ApiKeyForbidden("you are not a member of this workspace")
        _, role = membership

        requested = set(permissions)
        allowed = set(role.permissions)
        if minting_key is not None and "*" not in minting_key.permissions:
            allowed &= set(minting_key.permissions)
        if "*" not in allowed and not requested <= allowed:
            denied = sorted(requested - allowed)
            raise ApiKeyForbidden(f"cannot grant permissions you do not have: {', '.join(denied)}")

        raw = self.generate()
        key = ApiKey(
            workspace_id=workspace_id,
            name=name,
            key_prefix=self._prefix(raw),
            key_hash=self._hash(raw),
            permissions=sorted(requested),
            created_by_user_id=actor.id,
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

    async def list_api_keys(
        self, workspace_id: str, created_by_user_id: str
    ) -> list[ApiKey]:
        """Keys owned by one user in one workspace — never anyone else's."""
        stmt = (
            select(ApiKey)
            .where(
                ApiKey.workspace_id == workspace_id,
                ApiKey.created_by_user_id == created_by_user_id,
            )
            .order_by(ApiKey.created_at.desc())
        )
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
        """Resolve a raw bearer secret to an active key, or None."""
        stmt = select(ApiKey).where(ApiKey.key_hash == self._hash(raw))
        result = await self._session.execute(stmt)
        key = result.scalar_one_or_none()
        if key is None or key.revoked_at is not None:
            return None
        return key

    async def touch(self, key: ApiKey) -> None:
        """Record the last successful use of a key."""
        key.last_used_at = now_utc()
        await self._session.commit()
