from __future__ import annotations

import re
import uuid

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import EventBus
from src.events.publisher import publish_audit, publish_event
from src.events.subjects import Subjects
from src.models.agent import Agent
from src.models.workspace import Role
from src.settings import settings

_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


class AgentError(Exception):
    pass


class AgentNotFound(AgentError):
    pass


class AgentConflict(AgentError):
    pass


class AgentValidation(AgentError):
    pass


def _slugify(name: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    # collapse consecutive dashes
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or f"agent-{uuid.uuid4().hex[:8]}"


class AgentService:
    def __init__(self, session: AsyncSession, bus: EventBus | None = None, secret_store=None) -> None:
        self._session = session
        self._bus = bus
        self._secret_store = secret_store
        if self._secret_store is None:
            try:
                from src.container import Container  # lazy to avoid cycle

                # Use container's store if available; fallback to factory
                # importing here keeps tests that don't wire container working.
                from src.secrets.factory import build_secret_store

                self._secret_store = build_secret_store()
            except Exception:
                self._secret_store = None

    # ---------------------------------------------------------------- helpers

    async def _get_or_404(self, workspace_id: str, agent_id: str) -> Agent:
        agent = await self._session.get(Agent, agent_id)
        if agent is None or agent.workspace_id != workspace_id:
            raise AgentNotFound("agent not found")
        return agent

    async def _ensure_slug_unique(self, workspace_id: str, slug: str, exclude_id: str | None = None) -> None:
        stmt = select(Agent).where(Agent.workspace_id == workspace_id, Agent.slug == slug)
        if exclude_id:
            stmt = stmt.where(Agent.id != exclude_id)
        existing = await self._session.execute(stmt)
        if existing.scalar_one_or_none() is not None:
            raise AgentConflict("agent slug already exists in this workspace")

    async def _validate_role(self, workspace_id: str, role_id: str | None) -> None:
        if role_id is None:
            return
        role = await self._session.get(Role, role_id)
        if role is None or role.workspace_id != workspace_id:
            raise AgentValidation("role not found in workspace")

    def _validate_model(self, model: str | None) -> None:
        if model is None:
            return
        allow = [s.strip() for s in settings.agent_llm_providers.split(",") if s.strip()]
        if allow and model not in allow:
            raise AgentValidation(f"model not allowed: {model}")

    def _agent_dict(self, a: Agent) -> dict:
        return {
            "id": a.id,
            "workspace_id": a.workspace_id,
            "slug": a.slug,
            "name": a.name,
            "description": a.description,
            "avatar": a.avatar,
            "system_prompt": a.system_prompt,
            "model": a.model,
            "temperature": a.temperature,
            "max_tokens": a.max_tokens,
            "tool_allowlist": a.tool_allowlist,
            "mcp_servers": a.mcp_servers if a.mcp_servers is not None else [],
            "execution_target": a.execution_target,
            "role_id": a.role_id,
            "skills": a.skills if a.skills is not None else [],
            "is_active": a.is_active,
            "custom_data": a.custom_data if a.custom_data is not None else {},
            "created_by_user_id": a.created_by_user_id,
            "updated_by_user_id": a.updated_by_user_id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        }

    # ---------------------------------------------------------------- CRUD

    async def create_agent(
        self,
        workspace_id: str,
        *,
        data: dict,
        actor_user_id: str | None = None,
        ip_address: str | None = None,
    ) -> Agent:
        name = data.get("name")
        slug = data.get("slug") or _slugify(name or "")
        if not _SLUG_RE.match(slug):
            # slugify fallback if manual slug invalid
            slug = _slugify(slug)
            if not _SLUG_RE.match(slug):
                raise AgentValidation("invalid slug")
        await self._ensure_slug_unique(workspace_id, slug)
        await self._validate_role(workspace_id, data.get("role_id"))
        self._validate_model(data.get("model"))

        agent = Agent(
            workspace_id=workspace_id,
            slug=slug,
            name=name,
            description=data.get("description"),
            avatar=data.get("avatar"),
            system_prompt=data.get("system_prompt"),
            model=data.get("model"),
            temperature=data.get("temperature"),
            max_tokens=data.get("max_tokens"),
            tool_allowlist=data.get("tool_allowlist"),
            mcp_servers=data.get("mcp_servers") if data.get("mcp_servers") is not None else [],
            execution_target=data.get("execution_target"),
            role_id=data.get("role_id"),
            skills=data.get("skills") if data.get("skills") is not None else [],
            is_active=data.get("is_active") if data.get("is_active") is not None else True,
            custom_data=data.get("custom_data") if data.get("custom_data") is not None else {},
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
        )
        self._session.add(agent)
        await self._session.commit()
        await self._session.refresh(agent)
        await publish_event(
            self._bus,
            Subjects.AGENT_PROFILE_CHANGED,
            {"workspace_id": workspace_id, "agent_id": agent.id, "action": "created"},
            transient=True,
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="agent",
            resource_id=agent.id,
            action="agent.created",
            actor_user_id=actor_user_id,
            details={"slug": slug, "name": name},
            ip_address=ip_address,
        )
        return agent

    async def get_agent(self, workspace_id: str, agent_id: str) -> Agent:
        return await self._get_or_404(workspace_id, agent_id)

    async def update_agent(
        self,
        workspace_id: str,
        agent_id: str,
        *,
        data: dict,
        actor_user_id: str | None = None,
        ip_address: str | None = None,
    ) -> Agent:
        agent = await self._get_or_404(workspace_id, agent_id)
        if "slug" in data and data["slug"] is not None:
            slug = data["slug"]
            if not _SLUG_RE.match(slug):
                raise AgentValidation("invalid slug")
            if slug != agent.slug:
                await self._ensure_slug_unique(workspace_id, slug, exclude_id=agent.id)
            agent.slug = slug
        if "role_id" in data:
            await self._validate_role(workspace_id, data["role_id"])
            agent.role_id = data["role_id"]
        if "model" in data:
            self._validate_model(data["model"])
            agent.model = data["model"]
        # simple field updates (PATCH semantics — only when key present)
        for field in (
            "name",
            "description",
            "avatar",
            "system_prompt",
            "temperature",
            "max_tokens",
            "tool_allowlist",
            "mcp_servers",
            "execution_target",
            "skills",
            "is_active",
            "custom_data",
        ):
            if field in data:
                setattr(agent, field, data[field])
        if actor_user_id:
            agent.updated_by_user_id = actor_user_id
        await self._session.commit()
        await self._session.refresh(agent)
        await publish_event(
            self._bus,
            Subjects.AGENT_PROFILE_CHANGED,
            {"workspace_id": workspace_id, "agent_id": agent.id, "action": "updated"},
            transient=True,
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="agent",
            resource_id=agent.id,
            action="agent.updated",
            actor_user_id=actor_user_id,
            details={"updated_fields": list(data.keys())},
            ip_address=ip_address,
        )
        return agent

    async def delete_agent(
        self,
        workspace_id: str,
        agent_id: str,
        *,
        actor_user_id: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        agent = await self._get_or_404(workspace_id, agent_id)
        await self._session.delete(agent)
        await self._session.commit()
        # best-effort clean secrets for this agent
        if self._secret_store is not None:
            try:
                prefix = f"agent:{agent_id}:"
                records = await self._secret_store.list_for_workspace(workspace_id, prefix=prefix)
                for r in records:
                    await self._secret_store.delete(workspace_id=workspace_id, key=r.key)
            except Exception:
                pass
        await publish_event(
            self._bus,
            Subjects.AGENT_PROFILE_CHANGED,
            {"workspace_id": workspace_id, "agent_id": agent_id, "action": "deleted"},
            transient=True,
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="agent",
            resource_id=agent_id,
            action="agent.deleted",
            actor_user_id=actor_user_id,
            details={},
            ip_address=ip_address,
        )

    # ---------------------------------------------------------------- secrets

    def _logical_key(self, agent_id: str, env_key: str) -> str:
        if not _KEY_RE.match(env_key):
            raise AgentValidation("secret key must match ^[A-Z_][A-Z0-9_]*$")
        logical = f"agent:{agent_id}:{env_key}"
        if len(logical) > 400:
            raise AgentValidation("secret key too long (logical key exceeds 400 chars)")
        return logical

    async def list_secret_keys(self, workspace_id: str, agent_id: str) -> list[dict]:
        await self._get_or_404(workspace_id, agent_id)
        if self._secret_store is None:
            return []
        prefix = f"agent:{agent_id}:"
        records = await self._secret_store.list_for_workspace(workspace_id, prefix=prefix)
        # strip values
        out = []
        for r in records:
            # r.key is logical key; extract env var name
            env = r.key[len(prefix) :] if r.key.startswith(prefix) else r.key
            out.append({"key": env, "created_at": r.created_at.isoformat() if r.created_at else None})
        return out

    async def set_secret(
        self,
        workspace_id: str,
        agent_id: str,
        env_key: str,
        value: str,
        *,
        actor_user_id: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        await self._get_or_404(workspace_id, agent_id)
        logical = self._logical_key(agent_id, env_key)
        if self._secret_store is None:
            raise AgentError("secret store not configured")
        await self._secret_store.put(
            workspace_id=workspace_id, key=logical, value=value, kind="agent_env", label=env_key
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="agent",
            resource_id=agent_id,
            action="agent.secret.set",
            actor_user_id=actor_user_id,
            details={"key": env_key},
            ip_address=ip_address,
        )

    async def delete_secret(
        self,
        workspace_id: str,
        agent_id: str,
        env_key: str,
        *,
        actor_user_id: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        await self._get_or_404(workspace_id, agent_id)
        logical = self._logical_key(agent_id, env_key)
        if self._secret_store is None:
            raise AgentError("secret store not configured")
        await self._secret_store.delete(workspace_id=workspace_id, key=logical)
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="agent",
            resource_id=agent_id,
            action="agent.secret.deleted",
            actor_user_id=actor_user_id,
            details={"key": env_key},
            ip_address=ip_address,
        )
