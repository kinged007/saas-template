"""Deployment-wide admin surface (superuser only).

Unlike workspace-scoped routes, these are gated on `require_superuser`,
not on workspace RBAC — a superuser does not need membership in a
workspace to inspect it here.

Session-only: `require_superuser` rejects API keys, so every route here
requires a superuser's session token. The same applies to the
`/jobs/global*` family and the `/users/{id}` administration routes.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, apply_query, parse_query
from src.api.deps import get_container, require_superuser
from src.core.dates import iso_or_none
from src.db.session import get_db
from src.events.publisher import publish_audit
from src.models.audit import AuditLogEntry
from src.models.user_profile import UserProfile
from src.models.workspace import Role, User, Workspace, WorkspaceMember
from src.schemas.api import AdminUserUpdate, AdminWorkspaceFlags
from src.services.profile_helpers import escape_like, format_display_name
from src.services.serializers import user_to_dict, workspace_to_dict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_USER_SORTABLE = {"created_at", "email", "display_name"}
_USER_FILTERABLE = {"email", "is_active", "is_superuser"}
_WORKSPACE_SORTABLE = {"created_at", "name", "slug"}
_WORKSPACE_FILTERABLE = {"name", "slug"}
_AUDIT_SORTABLE = {"created_at", "action", "resource_type"}
_AUDIT_FILTERABLE = {"action", "resource_type", "actor_user_id", "workspace_id"}


def _uuid_or_404(value: str, label: str) -> str:
    # StringUUID's bind processor raises ValueError (-> 500) on a malformed id,
    # so validate before it reaches the query.
    try:
        uuid.UUID(value)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found") from None
    return value


def _admin_user_dict(u: User) -> dict:
    return {
        **user_to_dict(u),
        "is_active": bool(u.is_active),
        "created_at": iso_or_none(u.created_at),
    }


def _workspace_dict(w: Workspace) -> dict:
    return {**workspace_to_dict(w), "flags": dict(w.flags or {})}


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
        # "search" is a custom param, not a model filter. It arrives either as
        # ?search= or ?filter[search]= (legacy style); both parse as filters.
        searches = [v for k, _, v in spec.filters if k == "search"]
        if not searches and (plain := request.query_params.get("search")):
            searches = [plain]
        spec.filters = [f for f in spec.filters if f[0] != "search"]
        stmt = apply_query(stmt, User, spec, sortable=_USER_SORTABLE, filterable=_USER_FILTERABLE)
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    for term in searches:
        like = f"%{escape_like(term)}%"
        stmt = stmt.where(
            or_(
                User.email.ilike(like, escape="\\"),
                User.display_name.ilike(like, escape="\\"),
            )
        )
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    if not spec.sort_by:
        stmt = stmt.order_by(User.created_at.desc(), User.id.desc())
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [_admin_user_dict(u) for u in rows.scalars().all()]


@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    _=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, _uuid_or_404(user_id, "user"))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    stmt = (
        select(Workspace, Role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .join(Role, Role.id == WorkspaceMember.role_id)
        .where(WorkspaceMember.user_id == user_id)
        .order_by(Workspace.created_at.desc())
    )
    rows = await db.execute(stmt)
    workspaces = [
        {"id": w.id, "name": w.name, "slug": w.slug, "role": r.name} for w, r in rows.all()
    ]
    return {**_admin_user_dict(user), "workspaces": workspaces}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: AdminUserUpdate,
    request: Request,
    admin=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    user = await db.get(User, _uuid_or_404(user_id, "user"))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if user.id == admin.id and body.is_active is False:
        raise HTTPException(status.HTTP_409_CONFLICT, "cannot disable your own account")
    user.is_active = body.is_active
    await db.commit()
    action = "user.enabled" if body.is_active else "user.disabled"
    await publish_audit(
        container.bus,
        workspace_id=None,
        resource_type="user",
        resource_id=user.id,
        action=action,
        actor_user_id=admin.id,
        details={"email": user.email},
        ip_address=request.client.host if request.client else None,
    )
    return _admin_user_dict(user)


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
    if not spec.sort_by:
        stmt = stmt.order_by(Workspace.created_at.desc(), Workspace.id.desc())
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    workspaces = rows.scalars().all()
    counts = {}
    if workspaces:
        count_rows = await db.execute(
            select(WorkspaceMember.workspace_id, func.count())
            .where(WorkspaceMember.workspace_id.in_([w.id for w in workspaces]))
            .group_by(WorkspaceMember.workspace_id)
        )
        counts = dict(count_rows.all())
    response.headers["X-Total-Count"] = str(total)
    return [{**_workspace_dict(w), "member_count": counts.get(w.id, 0)} for w in workspaces]


@router.patch("/workspaces/{workspace_id}/flags")
async def update_workspace_flags(
    workspace_id: str,
    body: AdminWorkspaceFlags,
    request: Request,
    admin=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    workspace = await db.get(Workspace, _uuid_or_404(workspace_id, "workspace"))
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
    merged = {**(workspace.flags or {}), **body.flags}
    workspace.flags = merged
    await db.commit()
    await publish_audit(
        container.bus,
        workspace_id=workspace_id,
        resource_type="workspace",
        resource_id=workspace_id,
        action="workspace.flags_updated",
        actor_user_id=admin.id,
        details={"flags": body.flags},
        ip_address=request.client.host if request.client else None,
    )
    return _workspace_dict(workspace)


@router.get("/audit")
async def list_all_audit_logs(
    request: Request,
    response: Response,
    _=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AuditLogEntry, User, UserProfile, Workspace)
        .outerjoin(User, User.id == AuditLogEntry.actor_user_id)
        .outerjoin(UserProfile, UserProfile.user_id == User.id)
        .outerjoin(Workspace, Workspace.id == AuditLogEntry.workspace_id)
    )
    try:
        spec = parse_query(request)
        q = (request.query_params.get("q") or "").strip()
        stmt = apply_query(
            stmt, AuditLogEntry, spec, sortable=_AUDIT_SORTABLE, filterable=_AUDIT_FILTERABLE
        )
        if q:
            # Single cross-field search: substring match on workspace name,
            # user name/email, or action, plus exact match on any id column
            # (guarded: non-UUID terms must not reach UUID comparisons).
            like = f"%{q}%"
            clauses = [
                AuditLogEntry.action.ilike(like),
                Workspace.name.ilike(like),
                User.display_name.ilike(like),
                User.email.ilike(like),
            ]
            try:
                uuid.UUID(q)
            except ValueError:
                pass
            else:
                clauses.extend(
                    (
                        AuditLogEntry.id == q,
                        AuditLogEntry.workspace_id == q,
                        AuditLogEntry.actor_user_id == q,
                        AuditLogEntry.resource_id == q,
                    )
                )
            stmt = stmt.where(or_(*clauses))
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    if not spec.sort_by:
        stmt = stmt.order_by(AuditLogEntry.created_at.desc(), AuditLogEntry.id.desc())
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    out = []
    for entry, actor, profile, ws in rows.all():
        actor_name = None
        if actor is not None:
            if profile is not None and (profile.first_name or profile.last_name):
                actor_name = format_display_name(
                    profile.first_name, profile.last_name, actor.display_name
                )
            else:
                actor_name = actor.display_name
        out.append(
            {
                "id": entry.id,
                "workspace_id": entry.workspace_id,
                "workspace_name": ws.name if ws is not None else None,
                "actor_user_id": entry.actor_user_id,
                "actor_display_name": actor_name,
                "actor_email": actor.email if actor is not None else None,
                "resource_type": entry.resource_type,
                "resource_id": entry.resource_id,
                "action": entry.action,
                "details": entry.details,
                "ip_address": entry.ip_address,
                "created_at": iso_or_none(entry.created_at),
            }
        )
    return out
