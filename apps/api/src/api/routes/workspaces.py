from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, apply_query, parse_query
from src.api.deps import (
    get_container,
    get_current_user,
    require_permission,
)
from src.core.permissions import WORKSPACE_DELETE, WORKSPACE_READ, WORKSPACE_UPDATE
from src.db.session import get_db
from src.models.workspace import Workspace, WorkspaceMember
from src.schemas.api import WorkspaceCreate, WorkspaceUpdate
from src.services.serializers import workspace_to_dict
from src.services.workspaces import WorkspaceError, WorkspaceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_WORKSPACE_SORTABLE = {"name", "slug", "created_at"}
_WORKSPACE_FILTERABLE = {"name", "slug"}


@router.get("", response_model=list[dict])
async def list_workspaces(
    request: Request,
    response: Response,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    stmt = (
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id, WorkspaceMember.status == "active")
    )
    try:
        spec = parse_query(request)
        stmt = apply_query(
            stmt, Workspace, spec, sortable=_WORKSPACE_SORTABLE, filterable=_WORKSPACE_FILTERABLE
        )
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    memberships = await service.list_workspaces(user.id)
    roles_by_ws = {w.id: role.name for w, role, _ in memberships}
    response.headers["X-Total-Count"] = str(total)
    return [workspace_to_dict(w, role=roles_by_ws.get(w.id)) for w in rows.scalars().all()]


@router.post("", response_model=dict, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = WorkspaceService(db, container.bus)
    try:
        workspace = await service.create_workspace(
            name=body.name, slug=body.slug, description=body.description, owner=user
        )
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return workspace_to_dict(workspace, role="owner")


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    user=Depends(get_current_user),
    _=Depends(require_permission(WORKSPACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    workspace = await service.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
    membership = await service.get_membership(workspace_id, user.id)
    role = membership[1] if membership else None
    return workspace_to_dict(workspace, role=role.name if role else None)


@router.patch("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdate,
    user=Depends(require_permission(WORKSPACE_UPDATE)),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    workspace = await service.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
    if body.name is not None:
        workspace.name = body.name
    if body.description is not None:
        workspace.description = body.description
    await db.commit()
    return workspace_to_dict(workspace)


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: str,
    user=Depends(require_permission(WORKSPACE_DELETE)),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    workspace = await service.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
    await db.delete(workspace)
    await db.commit()
