from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user
from src.db.session import get_db
from src.schemas.api import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from src.services.auth import AuthError, AuthService
from src.services.serializers import user_to_dict, workspace_to_dict
from src.services.workspaces import WorkspaceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    service = AuthService(db)
    try:
        user = await service.register(
            email=body.email, password=body.password, display_name=body.display_name
        )
    except AuthError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    pair = await service.issue_tokens(user)
    return TokenResponse(**pair.__dict__)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    service = AuthService(db)
    try:
        user = await service.login_password(body.email, body.password)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    pair = await service.issue_tokens(user)
    return TokenResponse(**pair.__dict__)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    service = AuthService(db)
    try:
        pair = await service.rotate_refresh(body.refresh_token)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    return TokenResponse(**pair.__dict__)


@router.post("/logout", status_code=204)
async def logout(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> None:
    await AuthService(db).revoke_refresh(body.refresh_token)


@router.get("/me")
async def me(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    service = WorkspaceService(db)
    data = user_to_dict(user)
    memberships = await service.list_workspaces(user.id)
    data["workspaces"] = [
        workspace_to_dict(w, role=role.name, permissions=role.permissions)
        for w, role, _ in memberships
    ]
    data["permissions"] = sorted({p for _, role, _ in memberships for p in role.permissions})
    return data
