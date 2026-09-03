from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from dataclasses import dataclass
from typing import Any, Callable

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool
from pydantic_ai.exceptions import ModelRetry

logger = logging.getLogger(__name__)


@dataclass
class PlatformToolSpec:
    name: str
    permission: str
    mutates: bool
    description: str
    func: Callable[..., Any]


_REGISTRY: dict[str, PlatformToolSpec] = {}


def platform_tool(
    name: str,
    permission: str,
    *,
    mutates: bool = False,
    description: str = "",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        _REGISTRY[name] = PlatformToolSpec(
            name=name, permission=permission, mutates=mutates, description=description, func=fn
        )
        return fn

    return decorator


def _load_tools() -> None:
    # import every submodule of src.mcp.platform.tools so decorators run
    for m in pkgutil.iter_modules(["apps/api/src/mcp/platform/tools"]):
        try:
            importlib.import_module(f"src.mcp.platform.tools.{m.name}")
        except Exception:
            logger.exception("failed to load platform tool module %s", m.name)
    # also try the installed package path
    try:
        import src.mcp.platform.tools as _pkg  # noqa: F401

        for m in pkgutil.iter_modules(_pkg.__path__):  # type: ignore[attr-defined]
            try:
                importlib.import_module(f"src.mcp.platform.tools.{m.name}")
            except Exception:
                logger.exception("failed to load platform tool module %s", m.name)
    except Exception:
        pass


_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    _load_tools()


def get_registry() -> dict[str, PlatformToolSpec]:
    _ensure_loaded()
    return dict(_REGISTRY)


async def _audit_tool_call(
    *,
    workspace_id: str,
    agent_id: str,
    tool_name: str,
    permission: str,
    outcome: str,
    triggering_user_id: str | None,
    args_summary: dict | None = None,
) -> None:
    try:
        from src.db.session import SessionFactory
        from src.models.audit import AuditLogEntry

        async with SessionFactory() as session:
            session.add(
                AuditLogEntry(
                    workspace_id=workspace_id,
                    actor_user_id=triggering_user_id,
                    resource_type="agent_tool",
                    resource_id=agent_id,
                    action=f"tool.{tool_name}",
                    details={
                        "tool": tool_name,
                        "permission": permission,
                        "outcome": outcome,
                        "args": args_summary or {},
                    },
                )
            )
            await session.commit()
    except Exception:
        logger.exception("audit for tool %s failed", tool_name)


def _effective_perms(agent_perms: set[str], user_perms: set[str]) -> set[str]:
    # "*" means all — normalize
    if "*" in agent_perms or "*" in user_perms:
        # effective = intersection but "*" expands to the other's set
        # owner has "*" so effective = user_perms (still bounded by invoker)
        if "*" in agent_perms and "*" in user_perms:
            return {"*"}
        if "*" in agent_perms:
            return set(user_perms)
        return set(agent_perms)
    return agent_perms & user_perms


def build_tools(deps: Any) -> list[Tool]:
    """Wrap every registry entry as a pydantic_ai Tool with scope+audit gate.

    `deps` must expose .workspace_id, .agent_id, .triggering_user_id,
    .agent_perms (set[str]), .user_perms (set[str]).
    """
    _ensure_loaded()
    out: list[Tool] = []
    for spec in _REGISTRY.values():
        # capture spec in closure default
        _spec = spec

        # mutating tools require approval via deferred pattern
        requires_approval = _spec.mutates

        async def _wrapper(ctx: RunContext[Any], **kwargs: Any) -> Any:  # type: ignore[no-untyped-def]
            # scope comes from deps (AgentDeps) injected via ctx.deps
            d = getattr(ctx, "deps", None) or deps
            ws = getattr(d, "workspace_id", getattr(deps, "workspace_id", ""))
            ag = getattr(d, "agent_id", getattr(deps, "agent_id", ""))
            trig = getattr(d, "triggering_user_id", getattr(deps, "triggering_user_id", None))
            agent_perms: set[str] = set(getattr(d, "agent_perms", getattr(deps, "agent_perms", set())))
            user_perms: set[str] = set(getattr(d, "user_perms", getattr(deps, "user_perms", set())))

            # deny if agent has no role (empty perms) or tool perm not in effective scope
            if not agent_perms:
                await _audit_tool_call(
                    workspace_id=ws, agent_id=ag, tool_name=_spec.name, permission=_spec.permission, outcome="denied_no_role", triggering_user_id=trig, args_summary=kwargs
                )
                raise ModelRetry(f"tool {_spec.name} denied: agent has no role")

            effective = _effective_perms(agent_perms, user_perms)
            has = ("*" in effective) or (_spec.permission in effective)
            if not has:
                await _audit_tool_call(
                    workspace_id=ws, agent_id=ag, tool_name=_spec.name, permission=_spec.permission, outcome="denied_scope", triggering_user_id=trig, args_summary=kwargs
                )
                raise ModelRetry(f"tool {_spec.name} denied: missing permission {_spec.permission}")

            # execute
            try:
                # inject deps-derived identifiers into kwargs for the backing service
                # tool funcs are written to accept (ctx, deps, **kwargs) or (**kwargs)
                sig = inspect.signature(_spec.func)
                call_kwargs: dict[str, Any] = dict(kwargs)
                if "workspace_id" in sig.parameters and "workspace_id" not in call_kwargs:
                    call_kwargs["workspace_id"] = ws
                if "agent_id" in sig.parameters and "agent_id" not in call_kwargs:
                    call_kwargs["agent_id"] = ag
                if "triggering_user_id" in sig.parameters and "triggering_user_id" not in call_kwargs:
                    call_kwargs["triggering_user_id"] = trig
                if "deps" in sig.parameters:
                    call_kwargs["deps"] = d
                res = await _spec.func(**call_kwargs) if inspect.iscoroutinefunction(_spec.func) else _spec.func(**call_kwargs)
                await _audit_tool_call(
                    workspace_id=ws, agent_id=ag, tool_name=_spec.name, permission=_spec.permission, outcome="success", triggering_user_id=trig, args_summary=kwargs
                )
                return res
            except ModelRetry:
                raise
            except Exception as exc:
                await _audit_tool_call(
                    workspace_id=ws, agent_id=ag, tool_name=_spec.name, permission=_spec.permission, outcome="failed", triggering_user_id=trig, args_summary=kwargs
                )
                raise ModelRetry(f"tool {_spec.name} failed: {exc}") from exc

        _wrapper.__name__ = _spec.name.replace(".", "_")
        tool = Tool(
            _wrapper,
            name=_spec.name,
            description=_spec.description or _spec.func.__doc__ or _spec.name,
            requires_approval=requires_approval,
            takes_ctx=True,
        )
        out.append(tool)
    return out
