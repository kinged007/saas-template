from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_container, get_current_user
from src.core.dates import ensure_utc, now_utc
from src.core.security.ratelimit import get_auth_limiter
from src.db.session import get_db
from src.email import factory as email_factory
from src.email import templates
from src.schemas.api import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SessionRead,
    TokenResponse,
    TwoFactorDisable,
    TwoFactorLogin,
    TwoFactorSetupConfirm,
    VerifyEmailRequest,
)
from src.services.auth import AuthError, AuthService
from src.services.profiles import ProfileService
from src.services.serializers import profile_to_dict, user_to_dict, workspace_to_dict
from src.services.two_factor import TwoFactorError, TwoFactorService
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


def _user_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:500] if ua else None


def _limit_key(request: Request, email: str | None = None) -> str:
    ip = _client_ip(request) or "unknown"
    return f"{ip}:{(email or '').lower()}"


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
    pair = await service.issue_tokens(
        user, ip_address=_client_ip(request), user_agent=_user_agent(request)
    )
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
    key = _limit_key(request, body.email)
    get_auth_limiter().check(key)
    service = AuthService(db, container.bus)
    try:
        user = await service.login_password(
            body.email, body.password, ip_address=_client_ip(request)
        )
    except AuthError as exc:
        get_auth_limiter().fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    get_auth_limiter().reset(key)
    if user.totp_enabled:
        challenge = TwoFactorService(db, container.cipher, container.bus).issue_challenge(user.id)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"code": "2fa_required", "challenge_token": challenge},
        )
    pair = await service.issue_tokens(
        user, ip_address=_client_ip(request), user_agent=_user_agent(request)
    )
    return TokenResponse(**pair.__dict__)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> TokenResponse:
    get_auth_limiter().check(_limit_key(request))
    service = AuthService(db, container.bus)
    try:
        pair = await service.rotate_refresh(body.refresh_token, ip_address=_client_ip(request))
    except AuthError as exc:
        get_auth_limiter().fail(_limit_key(request))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    get_auth_limiter().reset(_limit_key(request))
    return TokenResponse(**pair.__dict__)


def _session_to_dict(row) -> dict:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
    }


@router.get("/sessions", response_model=list[SessionRead])
async def list_sessions(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    rows = await TwoFactorService(db, container.cipher, container.bus).list_sessions(user.id)
    now = now_utc()
    return [
        _session_to_dict(r)
        for r in rows
        if r.revoked_at is None and ensure_utc(r.expires_at) >= now
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> None:
    rows = await TwoFactorService(db, container.cipher, container.bus).list_sessions(user.id)
    row = next((r for r in rows if r.id == session_id), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    if row.revoked_at is None:
        row.revoked_at = now_utc()
        await db.commit()
        logger.info("session revoked user=%s session=%s", user.id, session_id)


@router.delete("/sessions", status_code=204)
async def revoke_all_sessions(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> None:
    rows = await TwoFactorService(db, container.cipher, container.bus).list_sessions(user.id)
    now = now_utc()
    changed = False
    for r in rows:
        if r.revoked_at is None and ensure_utc(r.expires_at) >= now:
            r.revoked_at = now
            changed = True
    if changed:
        await db.commit()
        logger.info("all sessions revoked user=%s", user.id)


@router.get("/2fa/status")
async def totp_status(
    user=Depends(get_current_user),
):
    return {"enabled": bool(user.totp_enabled)}


@router.post("/2fa/setup")
async def totp_setup(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        return await TwoFactorService(db, container.cipher, container.bus).start_setup(user)
    except TwoFactorError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.post("/2fa/enable")
async def totp_enable(
    body: TwoFactorSetupConfirm,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        codes = await TwoFactorService(db, container.cipher, container.bus).confirm_setup(
            user, setup_token=body.setup_token, code=body.code
        )
    except TwoFactorError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return {"backup_codes": codes}


@router.post("/2fa/disable", status_code=204)
async def totp_disable(
    body: TwoFactorDisable,
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> None:
    key = _limit_key(request, user.email)
    get_auth_limiter().check(key)
    try:
        await AuthService(db, container.bus).login_password(
            user.email, body.password, ip_address=_client_ip(request)
        )
    except AuthError as exc:
        get_auth_limiter().fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    get_auth_limiter().reset(key)
    await TwoFactorService(db, container.cipher, container.bus).disable(user)


@router.post("/2fa/backup-codes")
async def totp_backup_codes(
    body: TwoFactorDisable,
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    key = _limit_key(request, user.email)
    get_auth_limiter().check(key)
    try:
        await AuthService(db, container.bus).login_password(
            user.email, body.password, ip_address=_client_ip(request)
        )
    except AuthError as exc:
        get_auth_limiter().fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    get_auth_limiter().reset(key)
    try:
        codes = await TwoFactorService(db, container.cipher, container.bus).regenerate_backup_codes(
            user
        )
    except TwoFactorError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return {"backup_codes": codes}


@router.post("/2fa/login", response_model=TokenResponse)
async def totp_login(
    body: TwoFactorLogin,
    request: Request,
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> TokenResponse:
    svc = TwoFactorService(db, container.cipher, container.bus)
    try:
        user_id = svc.consume_challenge(body.challenge_token)
    except TwoFactorError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    key = _limit_key(request, user_id)
    get_auth_limiter().check(key)
    user = await AuthService(db, container.bus).get_user(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "account is disabled")
    try:
        ok = await svc.verify_login_code(user, code=body.code)
    except TwoFactorError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    if not ok:
        get_auth_limiter().fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid code")
    get_auth_limiter().reset(key)
    pair = await AuthService(db, container.bus).issue_tokens(
        user, ip_address=_client_ip(request), user_agent=_user_agent(request)
    )
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
