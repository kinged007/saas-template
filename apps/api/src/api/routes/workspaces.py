from __future__ import annotations

import json as _json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, apply_query, parse_query
from src.api.deps import (
    get_container,
    get_current_user,
    get_current_workspace_id,
    get_optional_workspace_id,
    require_existing_workspace,
    require_key_permission,
    require_permission,
    resolve_auth_principal,
)
from src.core.permissions import AUDIT_READ, WORKSPACE_DELETE, WORKSPACE_READ, WORKSPACE_UPDATE
from src.db.session import get_db
from src.models.workspace import Workspace, WorkspaceMember
from src.schemas.api import WorkspaceCreate, WorkspaceUpdate
from src.services.conversations import ConversationForbidden
from src.services.search_export import CSV_RESOURCES, SearchExportService
from src.services.serializers import workspace_to_dict
from src.services.workspaces import WorkspaceError, WorkspaceForbidden, WorkspaceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("/search")
async def search_workspace(
    q: str,
    user=Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WORKSPACE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    if not q or not q.strip() or len(q.strip()) > 200:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "q must be 1-200 characters")
    try:
        return await SearchExportService(db, container.bus).search(
            workspace_id=workspace_id, user_id=user.id, q=q.strip()
        )
    except ConversationForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None


@router.get("/export")
async def export_workspace(
    user=Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(AUDIT_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
    format: str = "json",
    resource: str = "members",
):
    if format not in ("json", "csv"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown format: {format} (choose from csv, json)",
        )
    service = SearchExportService(db, container.bus)
    try:
        bundle = await service.export_json(workspace_id=workspace_id, user_id=user.id)
    except ConversationForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    if format == "csv":
        if resource not in CSV_RESOURCES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"unknown resource: {resource} (choose from {', '.join(sorted(CSV_RESOURCES))})",
            )
        body = service.export_csv(bundle, resource)
        filename = f"workspace-{workspace_id}-{resource}.csv"
        return Response(
            content=body,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    body = _json.dumps(bundle)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="workspace-{workspace_id}-export.json"'
        },
    )


_WORKSPACE_SORTABLE = {"name", "slug", "created_at"}
_WORKSPACE_FILTERABLE = {"name", "slug"}


@router.get("", response_model=list[dict])
async def list_workspaces(
    request: Request,
    response: Response,
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(WORKSPACE_READ)),
    workspace_id: str | None = Depends(get_optional_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    if principal.api_key is not None:
        # API keys are workspace-scoped: surface exactly the key's workspace.
        workspace = await service.get_workspace(workspace_id)
        if workspace is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
        membership = await service.get_membership(workspace_id, user.id)
        role = membership[1] if membership else None
        response.headers["X-Total-Count"] = "1"
        return [workspace_to_dict(workspace, role=role.name if role else None)]
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
    request: Request,
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    if principal.api_key is not None:
        # API keys are workspace-scoped by definition; creating a brand-new
        # workspace is outside their scope and requires an interactive session.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "api keys cannot create workspaces")
    service = WorkspaceService(db, container.bus)
    try:
        workspace = await service.create_workspace(
            name=body.name,
            slug=body.slug,
            description=body.description,
            owner=user,
            ip_address=request.client.host if request.client else None,
        )
    except WorkspaceForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return workspace_to_dict(workspace, role="owner")


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    user=Depends(get_current_user),
    _=Depends(require_existing_workspace),
    _perm=Depends(require_permission(WORKSPACE_READ)),
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
    request: Request,
    user=Depends(get_current_user),
    _=Depends(require_existing_workspace),
    _perm=Depends(require_permission(WORKSPACE_UPDATE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = WorkspaceService(db, container.bus)
    try:
        workspace = await service.update_workspace(
            workspace_id,
            name=body.name,
            description=body.description,
            actor=user,
            ip_address=request.client.host if request.client else None,
        )
    except WorkspaceForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return workspace_to_dict(workspace)


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: str,
    request: Request,
    user=Depends(get_current_user),
    _=Depends(require_existing_workspace),
    _perm=Depends(require_permission(WORKSPACE_DELETE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = WorkspaceService(db, container.bus)
    try:
        await service.delete_workspace(
            workspace_id,
            actor=user,
            ip_address=request.client.host if request.client else None,
        )
    except WorkspaceForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
