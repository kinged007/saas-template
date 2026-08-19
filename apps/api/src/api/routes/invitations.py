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
from src.core.dates import ensure_utc, now_utc
from src.core.permissions import MEMBER_INVITE
from src.db.session import get_db
from src.models.core import Invitation
from src.models.workspace import Role
from src.schemas.api import InvitationCreate
from src.services.workspaces import (
    WorkspaceConflict,
    WorkspaceError,
    WorkspaceService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invitations", tags=["invitations"])

_INVITATION_FILTERABLE = {"status", "email"}
_INVITATION_SORTABLE = {"created_at", "status", "expires_at"}


def _invite_dict(i: Invitation) -> dict:
    expired = (
        i.status == "pending" and i.expires_at is not None and ensure_utc(i.expires_at) < now_utc()
    )
    return {
        "id": i.id,
        "workspace_id": i.workspace_id,
        "email": i.email,
        "role_id": i.role_id,
        "invited_by_user_id": i.invited_by_user_id,
        "token": i.token,
        "status": i.status,
        "expires_at": i.expires_at.isoformat() if i.expires_at else None,
        "accepted_at": i.accepted_at.isoformat() if i.accepted_at else None,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "expired": expired,
    }


@router.get("")
async def list_invitations(
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(MEMBER_INVITE)),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Invitation).where(Invitation.workspace_id == workspace_id)
    try:
        spec = parse_query(request)
        stmt = apply_query(
            stmt, Invitation, spec, sortable=_INVITATION_SORTABLE, filterable=_INVITATION_FILTERABLE
        )
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [_invite_dict(i) for i in rows.scalars().all()]


@router.post("", status_code=201)
async def create_invitation(
    body: InvitationCreate,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(MEMBER_INVITE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = WorkspaceService(db, container.bus)
    workspace = await service.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
    role = await db.get(Role, body.role_id)
    if role is None or role.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown role for this workspace")
    try:
        invite = await service.create_invitation(
            workspace=workspace, email=body.email, role=role, invited_by=user
        )
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _invite_dict(invite)


@router.delete("/{invitation_id}", status_code=204)
async def revoke_invitation(
    invitation_id: str,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(MEMBER_INVITE)),
    db: AsyncSession = Depends(get_db),
):
    try:
        await WorkspaceService(db).revoke_invitation(workspace_id, invitation_id)
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None


@router.post("/accept")
async def accept_invitation(
    token: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        workspace = await WorkspaceService(db, container.bus).accept_invitation(token, user)
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return {"workspace_id": workspace.id, "workspace_name": workspace.name}


@router.get("/mine")
async def my_invitations(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await WorkspaceService(db).list_received_invitations(user)
    return [
        {
            **_invite_dict(i),
            "workspace_name": w.name,
            "invited_by_name": u.display_name,
        }
        for i, w, u in rows
    ]


@router.post("/{invitation_id}/decline")
async def decline_invitation(
    invitation_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        invite = await WorkspaceService(db).decline_invitation(invitation_id, user)
    except WorkspaceConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except WorkspaceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return _invite_dict(invite)
