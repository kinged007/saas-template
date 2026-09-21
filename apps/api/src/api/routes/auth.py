from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_container, get_current_user
from src.db.session import get_db
from src.email import factory as email_factory
from src.email import templates
from src.schemas.api import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from src.services.auth import AuthError, AuthService
from src.services.profiles import ProfileService
from src.services.serializers import profile_to_dict, user_to_dict, workspace_to_dict
from src.services.workspaces import WorkspaceService
from src.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _frontend_url(path: str, token: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}{path}{token}"


async def _send_verification(service: AuthService, user) -> None:
    """Best-effort verification email; fail-closed (row kept, failure logged)."""
    if getattr(user, "email_verified_at", None) is not None:
        return
    raw = await service.request_verification(user)
    await email_factory.send_email(
        templates.email_verification(
            user.email, verify_url=_frontend_url("/verify-email?token=", raw)
        )
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _maybe_join_single_workspace(db: AsyncSession, container, user) -> None:
    if not settings.single_workspace:
        return
    await WorkspaceService(db, container.bus).join_single_workspace(user)


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> TokenResponse:
    service = AuthService(db, container.bus)
    # Validate naming: prefer first/last, fallback to deprecated display_name
    if not body.first_name and not body.last_name and not body.display_name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "first_name and last_name are required (or display_name deprecated)",
        )
    # If only one of first/last provided without the other, still allow but derive
    try:
        user = await service.register(
            email=body.email,
            password=body.password,
            first_name=body.first_name,
            last_name=body.last_name,
            display_name=body.display_name,
            ip_address=_client_ip(request),
        )
    except AuthError as exc:
        msg = str(exc)
        # Map missing names to 422, else 409
        if "first_name and last_name" in msg:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg) from None
        raise HTTPException(status.HTTP_409_CONFLICT, msg) from None
    pair = await service.issue_tokens(user)
    try:
        await _maybe_join_single_workspace(db, container, user)
    except Exception:
        logger.exception("failed to join single workspace for user %s", user.id)
    try:
        await _send_verification(service, user)
    except Exception:
        logger.exception("failed to send verification email for user %s", user.id)
    return TokenResponse(**pair.__dict__)


@router.post("/forgot-password", status_code=202)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> dict:
    # Always 202 — never reveal whether the email is registered.
    raw = await AuthService(db, container.bus).request_password_reset(
        str(body.email), ip_address=_client_ip(request)
    )
    if raw is not None:
        try:
            await email_factory.send_email(
                templates.password_reset(
                    str(body.email), reset_url=_frontend_url("/reset-password?token=", raw)
                )
            )
        except Exception:
            logger.exception("failed to send password-reset email for %s", body.email)
    return {"detail": "if an account exists for this email, a reset link was sent"}


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> dict:
    try:
        await AuthService(db, container.bus).reset_password(
            body.token, body.new_password, ip_address=_client_ip(request)
        )
    except AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return {"detail": "password updated"}


@router.post("/verify-email")
async def verify_email(
    body: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> dict:
    try:
        await AuthService(db, container.bus).verify_email(body.token)
    except AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return {"detail": "email verified"}


@router.post("/resend-verification", status_code=202)
async def resend_verification(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> dict:
    if getattr(user, "email_verified_at", None) is not None:
        return {"detail": "email already verified"}
    service = AuthService(db, container.bus)
    fresh = await db.get(type(user), user.id)
    try:
        await _send_verification(service, fresh or user)
    except Exception:
        logger.exception("failed to resend verification email for user %s", user.id)
    return {"detail": "if unverified, a verification link was sent"}


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
    await _maybe_join_single_workspace(db, container, user)
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
    if settings.single_workspace:
        # Toggling onto an existing deployment: oldest wins, rest stay hidden.
        single = await service.get_single_workspace()
        if single is not None:
            memberships = [m for m in memberships if m[0].id == single.id]
    data["workspaces"] = [
        workspace_to_dict(w, role=role.name, permissions=role.permissions)
        for w, role, _ in memberships
    ]
    data["permissions"] = sorted({p for _, role, _ in memberships for p in role.permissions})
    data["single_workspace"] = settings.single_workspace
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
