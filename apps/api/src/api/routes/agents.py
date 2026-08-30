from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, apply_query, parse_query
from src.api.deps import get_container, get_current_user, get_current_workspace_id, require_permission
from src.core.permissions import AGENT_MANAGE, AGENT_READ
from src.db.session import get_db
from src.models.agent import Agent
from src.schemas.api import AgentCreate, AgentSecretPut, AgentUpdate
from src.services.agents import AgentConflict, AgentNotFound, AgentService, AgentValidation

router = APIRouter(prefix="/agents", tags=["agents"])

_AGENT_FILTERABLE = {"name", "slug", "model", "is_active", "execution_target"}
_AGENT_SORTABLE = {"name", "slug", "created_at", "model"}


def _agent_dict(a: Agent) -> dict:
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


@router.get("")
async def list_agents(
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(AGENT_READ)),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Agent).where(Agent.workspace_id == workspace_id)
    try:
        spec = parse_query(request)
        stmt = apply_query(stmt, Agent, spec, sortable=_AGENT_SORTABLE, filterable=_AGENT_FILTERABLE)
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [_agent_dict(r) for r in rows.scalars().all()]


@router.post("", status_code=201)
async def create_agent(
    body: AgentCreate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(AGENT_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    svc = AgentService(db, container.bus, secret_store=container.secret_store)
    try:
        agent = await svc.create_agent(
            workspace_id,
            data=body.model_dump(exclude_unset=True),
            actor_user_id=user.id,
            ip_address=request.client.host if request.client else None,
        )
    except AgentConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except AgentValidation as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return _agent_dict(agent)


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(AGENT_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    svc = AgentService(db, container.bus, secret_store=container.secret_store)
    try:
        agent = await svc.get_agent(workspace_id, agent_id)
    except AgentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return _agent_dict(agent)


@router.patch("/{agent_id}")
async def patch_agent(
    agent_id: str,
    body: AgentUpdate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(AGENT_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    svc = AgentService(db, container.bus, secret_store=container.secret_store)
    try:
        agent = await svc.update_agent(
            workspace_id,
            agent_id,
            data=body.model_dump(exclude_unset=True),
            actor_user_id=user.id,
            ip_address=request.client.host if request.client else None,
        )
    except AgentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except AgentConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except AgentValidation as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return _agent_dict(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: str,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(AGENT_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    svc = AgentService(db, container.bus, secret_store=container.secret_store)
    try:
        await svc.delete_agent(
            workspace_id, agent_id, actor_user_id=user.id, ip_address=request.client.host if request.client else None
        )
    except AgentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return None


# ---- secrets (write-only; list returns keys + created_at only)


@router.get("/{agent_id}/secrets")
async def list_agent_secrets(
    agent_id: str,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(AGENT_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    svc = AgentService(db, container.bus, secret_store=container.secret_store)
    try:
        return await svc.list_secret_keys(workspace_id, agent_id)
    except AgentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None


@router.put("/{agent_id}/secrets/{key}", status_code=204)
async def put_agent_secret(
    agent_id: str,
    key: str,
    body: AgentSecretPut,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(AGENT_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    svc = AgentService(db, container.bus, secret_store=container.secret_store)
    try:
        await svc.set_secret(
            workspace_id, agent_id, key, body.value, actor_user_id=user.id, ip_address=request.client.host if request.client else None
        )
    except AgentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except AgentValidation as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return None


@router.delete("/{agent_id}/secrets/{key}", status_code=204)
async def delete_agent_secret(
    agent_id: str,
    key: str,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(AGENT_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    svc = AgentService(db, container.bus, secret_store=container.secret_store)
    try:
        await svc.delete_secret(
            workspace_id, agent_id, key, actor_user_id=user.id, ip_address=request.client.host if request.client else None
        )
    except AgentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except AgentValidation as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return None
