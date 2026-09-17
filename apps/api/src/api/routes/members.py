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
from src.core.permissions import MEMBER_DELETE, MEMBER_READ, MEMBER_UPDATE
from src.db.session import get_db
from src.models.user_profile import UserProfile
from src.models.workspace import Role, User, WorkspaceMember
from src.schemas.api import MemberRoleUpdate
from src.services.profile_helpers import format_display_name
from src.services.serializers import user_to_dict
from src.services.workspaces import (
    WorkspaceConflict,
    WorkspaceError,
    WorkspaceForbidden,
    WorkspaceService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/members", tags=["members"])

_MEMBER_FILTERABLE = {"status", "role_id"}
_MEMBER_SORTABLE = {"created_at", "status"}


def _member_dict(
    member: WorkspaceMember, user: User, role: Role, profile: UserProfile | None = None
) -> dict:
    data = user_to_dict(user)
    # Prefer profile-derived display name (First L.) if profile available
    if profile is not None and (profile.first_name or profile.last_name):
        derived = format_display_name(profile.first_name, profile.last_name, user.display_name)
        if derived:
            data["display_name"] = derived
        data["first_name"] = profile.first_name
        data["last_name"] = profile.last_name
    else:
        data["first_name"] = profile.first_name if profile else None
        data["last_name"] = profile.last_name if profile else None
    data.update(
        {
            "membership_id": member.id,
            "role_id": role.id,
            "role": role.name,
            "status": member.status,
            "joined_at": member.created_at.isoformat() if member.created_at else None,
        }
    )
    return data


@router.get("")
async def list_members(
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(MEMBER_READ)),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(WorkspaceMember, User, Role, UserProfile)
        .join(User, User.id == WorkspaceMember.user_id)
        .join(Role, Role.id == WorkspaceMember.role_id)
        .outerjoin(UserProfile, UserProfile.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace_id)
    )
    try:
        spec = parse_query(request)
        stmt = apply_query(
            stmt, WorkspaceMember, spec, sortable=_MEMBER_SORTABLE, filterable=_MEMBER_FILTERABLE
        )
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [_member_dict(m, u, r, p) for m, u, r, p in rows.all()]


@router.patch("/{membership_id}")
async def set_member_role(
    membership_id: str,
    body: MemberRoleUpdate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(MEMBER_UPDATE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        member = await WorkspaceService(db, container.bus).set_member_role(
            workspace_id,
            membership_id,
            body.role_id,
            actor=user,
            ip_address=request.client.host if request.client else None,
        )
    except WorkspaceForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except WorkspaceConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return {"id": member.id, "role_id": member.role_id}


@router.post("/{membership_id}/suspend")
async def suspend_member(
    membership_id: str,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(MEMBER_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        member = await WorkspaceService(db, container.bus).suspend_member(
            workspace_id,
            membership_id,
            actor=user,
            ip_address=request.client.host if request.client else None,
        )
    except WorkspaceForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except WorkspaceConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return {"id": member.id, "status": member.status}


@router.post("/{membership_id}/reactivate")
async def reactivate_member(
    membership_id: str,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(MEMBER_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        member = await WorkspaceService(db, container.bus).reactivate_member(
            workspace_id,
            membership_id,
            actor=user,
            ip_address=request.client.host if request.client else None,
        )
    except WorkspaceForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except WorkspaceConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return {"id": member.id, "status": member.status}


@router.delete("/{membership_id}", status_code=204)
async def remove_member(
    membership_id: str,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(MEMBER_DELETE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        await WorkspaceService(db, container.bus).remove_member(
            workspace_id,
            membership_id,
            actor=user,
            ip_address=request.client.host if request.client else None,
        )
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
