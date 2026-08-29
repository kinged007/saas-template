from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_container, get_current_user
from src.db.session import get_db
from src.schemas.api import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from src.services.auth import AuthError, AuthService
from src.services.profiles import ProfileService
from src.services.serializers import profile_to_dict, user_to_dict, workspace_to_dict
from src.services.workspaces import WorkspaceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> TokenResponse:
    service = AuthService(db, container.bus)
    try:
        user = await service.register(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            ip_address=_client_ip(request),
        )
    except AuthError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    pair = await service.issue_tokens(user)
    return TokenResponse(**pair.__dict__)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> TokenResponse:
    service = AuthService(db, container.bus)
    try:
        user = await service.login_password(
            body.email, body.password, ip_address=_client_ip(request)
        )
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    pair = await service.issue_tokens(user)
    return TokenResponse(**pair.__dict__)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> TokenResponse:
    service = AuthService(db, container.bus)
    try:
        pair = await service.rotate_refresh(body.refresh_token, ip_address=_client_ip(request))
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    return TokenResponse(**pair.__dict__)


@router.post("/logout", status_code=204)
async def logout(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> None:
    await AuthService(db, container.bus).revoke_refresh(
        body.refresh_token, ip_address=_client_ip(request)
    )


@router.get("/me")
async def me(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = WorkspaceService(db)
    data = user_to_dict(user)
    memberships = await service.list_workspaces(user.id)
    data["workspaces"] = [
        workspace_to_dict(w, role=role.name, permissions=role.permissions)
        for w, role, _ in memberships
    ]
    data["permissions"] = sorted({p for _, role, _ in memberships for p in role.permissions})
    # Embed profile (lazy create)
    try:
        profile = await ProfileService(db, container.bus).get_or_create(user.id)
        data["profile"] = profile_to_dict(profile)
    except Exception:
        logger.exception("failed to embed profile for user %s", user.id)
        # Fallback: minimal empty profile
        data["profile"] = {
            "id": user.id,
            "user_id": user.id,
            "first_name": None,
            "last_name": None,
            "bio": None,
            "phone_number": None,
            "timezone": None,
            "locale": None,
            "date_of_birth": None,
            "website_url": None,
            "location": None,
            "custom_data": {},
            "created_at": None,
            "updated_at": None,
        }
    return data
