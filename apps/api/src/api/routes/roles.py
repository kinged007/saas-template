from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, apply_query, parse_query
from src.api.deps import (
    get_container,
    get_current_user,
    get_current_workspace_id,
    require_permission,
)
from src.core.permissions import ALL_PERMISSIONS, ROLE_MANAGE, ROLE_READ
from src.db.session import get_db
from src.models.workspace import Role
from src.schemas.api import RoleCreate
from src.services.workspaces import WorkspaceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/roles", tags=["roles"])

_ROLE_FILTERABLE = {"name", "system"}
_ROLE_SORTABLE = {"name", "created_at"}


def _role_dict(r: Role) -> dict:
    return {
        "id": r.id,
        "workspace_id": r.workspace_id,
        "name": r.name,
        "description": r.description,
        "permissions": r.permissions,
        "system": r.system,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("")
async def list_roles(
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(ROLE_READ)),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Role).where(Role.workspace_id == workspace_id)
    try:
        spec = parse_query(request)
        stmt = apply_query(stmt, Role, spec, sortable=_ROLE_SORTABLE, filterable=_ROLE_FILTERABLE)
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [_role_dict(r) for r in rows.scalars().all()]


@router.get("/permission-catalog")
async def permission_catalog() -> dict:
    return {"permissions": ALL_PERMISSIONS}


@router.post("", status_code=201)
async def create_role(
    body: RoleCreate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(ROLE_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    role = await WorkspaceService(db, container.bus).create_custom_role(
        workspace_id,
        name=body.name,
        description=body.description,
        permissions=body.permissions,
        actor=user,
        ip_address=request.client.host if request.client else None,
    )
    return _role_dict(role)


@router.get("/{role_id}")
async def get_role(
    role_id: str,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(ROLE_READ)),
    db: AsyncSession = Depends(get_db),
):
    role = await db.get(Role, role_id)
    if role is None or role.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "role not found")
    return _role_dict(role)
