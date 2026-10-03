from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, apply_query, parse_query
from src.api.deps import (
    get_container,
    get_current_user,
    get_current_workspace_id,
    require_permission,
)
from src.core.permissions import ALL_PERMISSIONS, ROLE_CREATE, ROLE_READ
from src.db.session import get_db
from src.models.workspace import Role
from src.schemas.api import RoleCreate, RoleUpdate
from src.services.workspaces import (
    WorkspaceConflict,
    WorkspaceError,
    WorkspaceForbidden,
    WorkspaceNotFound,
    WorkspaceService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/roles", tags=["roles"])

_ROLE_FILTERABLE = {"name", "system"}
_ROLE_SORTABLE = {"name", "created_at"}

# Rank: a role whose lower-cased name is a DEFAULT_ROLES entry gets that
# entry's index, everything else ranks last. Ordering here rather than on the
# client so it holds across a page boundary: the system block keeps its default
# roles contiguous, and every role *list* surface agrees by construction (the
# export orders roles on its own). Contiguity comes from the rank, not from the
# order key — the sort and the row lock in `update_role` are separate steps, so
# a concurrent rename can still interleave. Names are unique only by exact
# match, so a custom role differing from a system name in case alone joins that
# rank group; #257 re-keys the rank on Role.system.
_ROLE_RANK = case(
    {name: i for i, name in enumerate(WorkspaceService.DEFAULT_ROLES)},
    value=func.lower(Role.name),
    else_=len(WorkspaceService.DEFAULT_ROLES),
)


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
    stmt = select(Role).where(Role.workspace_id == workspace_id).order_by(_ROLE_RANK)
    try:
        spec = parse_query(request)
        stmt = apply_query(stmt, Role, spec, sortable=_ROLE_SORTABLE, filterable=_ROLE_FILTERABLE)
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    # A client sorter is a tiebreak within the rank groups, not an override:
    # it is appended after _ROLE_RANK. Name last keeps the order total, so
    # paging cannot repeat or drop a row.
    stmt = stmt.order_by(Role.name).offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [_role_dict(r) for r in rows.scalars().all()]


@router.get("/permission-catalog")
async def permission_catalog(
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(ROLE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Full registry plus the permissions this caller may assign to a role.

    `permissions` is the catalog intersected with the caller's own role
    (`"*"` implies the full catalog) — same capping semantics as
    `GET /api-keys/effective-permissions`. The single source for the roles
    matrix and the New/Edit role dialogs."""
    membership = await WorkspaceService(db).get_membership(workspace_id, user.id, active_only=True)
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "you are not a member of this workspace")
    _, role = membership
    assignable = (
        sorted(ALL_PERMISSIONS)
        if "*" in role.permissions
        # Intersect against ALL_PERMISSIONS (not the full registry): a stale
        # role row holding a legacy key-only scope must not resurface it here.
        else sorted(set(role.permissions) & set(ALL_PERMISSIONS))
    )
    return {"catalog": sorted(ALL_PERMISSIONS), "permissions": assignable}


@router.post("", status_code=201)
async def create_role(
    body: RoleCreate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(ROLE_CREATE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        role = await WorkspaceService(db, container.bus).create_custom_role(
            workspace_id,
            name=body.name,
            description=body.description,
            permissions=body.permissions,
            actor=user,
            ip_address=request.client.host if request.client else None,
        )
    except WorkspaceForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except WorkspaceConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return _role_dict(role)


# ROLE_CREATE is the single custom-role writer guard (no ROLE_UPDATE/ROLE_DELETE
# exist by design) — it covers both create and update below.
@router.patch("/{role_id}")
async def update_role(
    role_id: str,
    body: RoleUpdate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(ROLE_CREATE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        role = await WorkspaceService(db, container.bus).update_role(
            workspace_id,
            role_id,
            name=body.name,
            description=body.description,
            permissions=body.permissions,
            actor=user,
            ip_address=request.client.host if request.client else None,
        )
    except WorkspaceForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except WorkspaceConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except WorkspaceNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return _role_dict(role)


@router.get("/{role_id}")
async def get_role(
    role_id: str,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(ROLE_READ)),
    db: AsyncSession = Depends(get_db),
):
    try:
        role = await WorkspaceService(db).get_role(workspace_id, role_id)
    except WorkspaceNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return _role_dict(role)
