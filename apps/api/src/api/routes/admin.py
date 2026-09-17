"""Superuser-only administration: user lookup/disable, workspace list, audit view."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, apply_query, parse_query
from src.api.deps import get_container, require_superuser
from src.db.session import get_db
from src.events.publisher import publish_audit
from src.models.audit import AuditLogEntry
from src.models.workspace import Role, User, Workspace, WorkspaceMember
from src.services.serializers import user_to_dict, workspace_to_dict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_USER_SORTABLE = {"created_at", "email", "display_name"}
_USER_FILTERABLE = {"email", "display_name", "is_active", "is_superuser"}
_WORKSPACE_SORTABLE = {"name", "slug", "created_at"}
_WORKSPACE_FILTERABLE = {"name", "slug"}
_AUDIT_SORTABLE = {"created_at", "action", "resource_type"}
_AUDIT_FILTERABLE = {"action", "resource_type", "actor_user_id", "workspace_id"}


class UserActiveUpdate(BaseModel):
    is_active: bool


async def _memberships_by_user(
    db: AsyncSession, user_id: str
) -> list[tuple[Workspace, str]]:
    stmt = (
        select(Workspace, Role.name)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .join(Role, Role.id == WorkspaceMember.role_id)
        .where(WorkspaceMember.user_id == user_id)
        .order_by(Workspace.created_at.desc())
    )
    return [(w, role_name) for w, role_name in (await db.execute(stmt)).all()]


@router.get("/users")
async def list_users(
    request: Request,
    response: Response,
    _=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User)
    try:
        spec = parse_query(request)
        stmt = apply_query(stmt, User, spec, sortable=_USER_SORTABLE, filterable=_USER_FILTERABLE)
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    stmt = stmt.order_by(User.created_at.desc()).offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [{**user_to_dict(u), "is_active": u.is_active} for u in rows.scalars().all()]


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: str,
    _=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    workspaces = [
        {"id": w.id, "name": w.name, "slug": w.slug, "role": role}
        for w, role in await _memberships_by_user(db, user.id)
    ]
    return {**user_to_dict(user), "is_active": user.is_active, "workspaces": workspaces}


@router.patch("/users/{user_id}")
async def set_user_active(
    user_id: str,
    body: UserActiveUpdate,
    request: Request,
    admin=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "cannot disable your own account")
    user.is_active = body.is_active
    await db.commit()
    await publish_audit(
        container.bus,
        workspace_id=None,
        resource_type="user",
        resource_id=user.id,
        action="user.disabled" if not body.is_active else "user.reenabled",
        actor_user_id=admin.id,
        details={"email": user.email},
        ip_address=request.client.host if request.client else None,
    )
    return {**user_to_dict(user), "is_active": user.is_active}


@router.get("/workspaces")
async def list_all_workspaces(
    request: Request,
    response: Response,
    _=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Workspace)
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
    response.headers["X-Total-Count"] = str(total)
    out = []
    for w in rows.scalars().all():
        members = await db.execute(
            select(func.count()).select_from(WorkspaceMember).where(
                WorkspaceMember.workspace_id == w.id
            )
        )
        out.append({**workspace_to_dict(w), "member_count": members.scalar_one(), "flags": w.flags})
    return out


@router.get("/audit")
async def list_all_audit(
    request: Request,
    response: Response,
    _=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLogEntry)
    try:
        spec = parse_query(request)
        stmt = apply_query(
            stmt, AuditLogEntry, spec, sortable=_AUDIT_SORTABLE, filterable=_AUDIT_FILTERABLE
        )
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    if not spec.sort_by:
        stmt = stmt.order_by(AuditLogEntry.created_at.desc(), AuditLogEntry.id.desc())
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [
        {
            "id": e.id,
            "workspace_id": e.workspace_id,
            "actor_user_id": e.actor_user_id,
            "resource_type": e.resource_type,
            "resource_id": e.resource_id,
            "action": e.action,
            "details": e.details,
            "ip_address": e.ip_address,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows.scalars().all()
    ]
