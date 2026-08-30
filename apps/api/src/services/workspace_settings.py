from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import EventBus
from src.events.publisher import publish_audit
from src.models.workspace_setting import WorkspaceSetting

SENSITIVE_KEYS = {"agents.sandbox.vercel_token"}

VALID_KEYS: dict[str, dict] = {
    "agents.default_model": {"type": "string", "max_len": 100, "allow_empty": True},
    "agents.default_runner": {"type": "enum", "values": ["local", "vercel"]},
    "agents.sandbox.vercel_team_id": {"type": "string", "max_len": 100, "allow_empty": True},
    "agents.sandbox.vercel_token": {"type": "secret", "max_len": 10000, "sensitive": True},
    "agents.sandbox.timeout_seconds": {"type": "int", "min": 1, "max": 3600},
    "agents.memory_enabled": {"type": "bool"},
    "agents.permission_ttl": {"type": "int", "min": 60, "max": 86400},
}


class WorkspaceSettingsError(Exception):
    pass


class WorkspaceSettingsNotFound(WorkspaceSettingsError):
    pass


class WorkspaceSettingsValidation(WorkspaceSettingsError):
    pass


def _validate(key: str, value) -> None:
    spec = VALID_KEYS.get(key)
    if spec is None:
        raise WorkspaceSettingsValidation(f"unknown setting key: {key}")
    t = spec["type"]
    if t == "string":
        if value is None and spec.get("allow_empty"):
            return
        if not isinstance(value, str):
            raise WorkspaceSettingsValidation(f"{key} must be a string")
        if len(value) > spec["max_len"]:
            raise WorkspaceSettingsValidation(f"{key} too long (max {spec['max_len']})")
    elif t == "secret":
        if not isinstance(value, str):
            raise WorkspaceSettingsValidation(f"{key} must be a string")
        if len(value) > spec["max_len"]:
            raise WorkspaceSettingsValidation(f"{key} too long")
        if not value.strip():
            raise WorkspaceSettingsValidation(f"{key} cannot be empty")
    elif t == "enum":
        if value is None:
            return
        if value not in spec["values"]:
            raise WorkspaceSettingsValidation(f"{key} must be one of {spec['values']}")
    elif t == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise WorkspaceSettingsValidation(f"{key} must be an integer")
        if value < spec["min"] or value > spec["max"]:
            raise WorkspaceSettingsValidation(f"{key} must be between {spec['min']} and {spec['max']}")
    elif t == "bool":
        if not isinstance(value, bool):
            raise WorkspaceSettingsValidation(f"{key} must be a boolean")
    else:
        raise WorkspaceSettingsValidation(f"unknown type for {key}")


def _secret_logical_key(workspace_id: str, key: str) -> str:
    return f"workspace:{workspace_id}:setting:{key}"


class WorkspaceSettingsService:
    def __init__(self, session: AsyncSession, bus: EventBus | None = None, secret_store=None) -> None:
        self._session = session
        self._bus = bus
        self._secret_store = secret_store
        if self._secret_store is None:
            try:
                from src.secrets.factory import build_secret_store

                self._secret_store = build_secret_store()
            except Exception:
                self._secret_store = None

    async def list_settings(self, workspace_id: str) -> list[dict]:
        result = await self._session.execute(
            select(WorkspaceSetting).where(WorkspaceSetting.workspace_id == workspace_id).order_by(WorkspaceSetting.key.asc())
        )
        rows = list(result.scalars().all())
        out = []
        for r in rows:
            if r.key in SENSITIVE_KEYS:
                has_secret = False
                if self._secret_store is not None:
                    try:
                        rec = await self._secret_store.get(workspace_id=workspace_id, key=_secret_logical_key(workspace_id, r.key))
                        has_secret = rec is not None
                    except Exception:
                        has_secret = bool(r.value and isinstance(r.value, dict) and r.value.get("secret_ref"))
                else:
                    has_secret = bool(r.value and isinstance(r.value, dict) and r.value.get("secret_ref"))
                masked = {"has_value": bool(has_secret)}
            else:
                masked = r.value
            out.append(
                {
                    "key": r.key,
                    "value": masked,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    "updated_by_user_id": r.updated_by_user_id,
                }
            )
        return out

    async def get_setting(self, workspace_id: str, key: str) -> dict:
        if key not in VALID_KEYS:
            raise WorkspaceSettingsValidation(f"unknown setting key: {key}")
        result = await self._session.execute(
            select(WorkspaceSetting).where(WorkspaceSetting.workspace_id == workspace_id, WorkspaceSetting.key == key)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise WorkspaceSettingsNotFound(f"setting {key} not found")
        if key in SENSITIVE_KEYS:
            has_secret = False
            if self._secret_store is not None:
                try:
                    rec = await self._secret_store.get(workspace_id=workspace_id, key=_secret_logical_key(workspace_id, key))
                    has_secret = rec is not None
                except Exception:
                    has_secret = bool(row.value and isinstance(row.value, dict) and row.value.get("secret_ref"))
            else:
                has_secret = bool(row.value and isinstance(row.value, dict) and row.value.get("secret_ref"))
            value = {"has_value": has_secret}
        else:
            value = row.value
        return {"key": row.key, "value": value, "updated_at": row.updated_at.isoformat() if row.updated_at else None, "updated_by_user_id": row.updated_by_user_id}

    async def upsert(
        self, workspace_id: str, key: str, value, *, actor_user_id: str | None = None, ip_address: str | None = None
    ) -> dict:
        # Treat None as "unset" → delete existing if any, then return 404-like? Instead store deletion via DELETE.
        # For PUT with null, interpret as delete to keep DB NOT NULL.
        if value is None:
            # delete if exists, else create empty? For enum allow_empty, None means clear → delete row.
            result = await self._session.execute(
                select(WorkspaceSetting).where(WorkspaceSetting.workspace_id == workspace_id, WorkspaceSetting.key == key)
            )
            row = result.scalar_one_or_none()
            if row is not None:
                if key in SENSITIVE_KEYS and self._secret_store is not None:
                    try:
                        await self._secret_store.delete(workspace_id=workspace_id, key=_secret_logical_key(workspace_id, key))
                    except Exception:
                        pass
                await self._session.delete(row)
                await self._session.commit()
                await publish_audit(
                    self._bus,
                    workspace_id=workspace_id,
                    resource_type="workspace_setting",
                    resource_id=key,
                    action="workspace_setting.deleted",
                    actor_user_id=actor_user_id,
                    details={"key": key},
                    ip_address=ip_address,
                )
            return {"key": key, "value": None, "updated_at": None, "updated_by_user_id": actor_user_id}
        _validate(key, value)
        is_sensitive = key in SENSITIVE_KEYS
        stored_value: dict
        if is_sensitive:
            if self._secret_store is None:
                raise WorkspaceSettingsError("secret store not configured")
            logical = _secret_logical_key(workspace_id, key)
            await self._secret_store.put(workspace_id=workspace_id, key=logical, value=str(value), kind="workspace_setting", label=key)
            stored_value = {"secret_ref": logical, "has_value": True}
        else:
            stored_value = value
        # upsert row
        result = await self._session.execute(
            select(WorkspaceSetting).where(WorkspaceSetting.workspace_id == workspace_id, WorkspaceSetting.key == key)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = WorkspaceSetting(workspace_id=workspace_id, key=key, value=stored_value, updated_by_user_id=actor_user_id)
            self._session.add(row)
        else:
            row.value = stored_value
            row.updated_by_user_id = actor_user_id
        await self._session.commit()
        await self._session.refresh(row)
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="workspace_setting",
            resource_id=key,
            action="workspace_setting.updated",
            actor_user_id=actor_user_id,
            details={"key": key},
            ip_address=ip_address,
        )
        # return masked
        if is_sensitive:
            return {"key": key, "value": {"has_value": True}, "updated_at": row.updated_at.isoformat() if row.updated_at else None, "updated_by_user_id": row.updated_by_user_id}
        return {"key": key, "value": stored_value, "updated_at": row.updated_at.isoformat() if row.updated_at else None, "updated_by_user_id": row.updated_by_user_id}

    async def delete_setting(self, workspace_id: str, key: str, *, actor_user_id: str | None = None, ip_address: str | None = None) -> None:
        if key not in VALID_KEYS:
            raise WorkspaceSettingsValidation(f"unknown setting key: {key}")
        result = await self._session.execute(
            select(WorkspaceSetting).where(WorkspaceSetting.workspace_id == workspace_id, WorkspaceSetting.key == key)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise WorkspaceSettingsNotFound(f"setting {key} not found")
        if key in SENSITIVE_KEYS and self._secret_store is not None:
            try:
                await self._secret_store.delete(workspace_id=workspace_id, key=_secret_logical_key(workspace_id, key))
            except Exception:
                pass
        await self._session.delete(row)
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="workspace_setting",
            resource_id=key,
            action="workspace_setting.deleted",
            actor_user_id=actor_user_id,
            details={"key": key},
            ip_address=ip_address,
        )
