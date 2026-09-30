from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import (
    AuthPrincipal,
    get_container,
    get_current_user,
    require_session_user,
    resolve_auth_principal,
)
from src.core.dates import ensure_utc, now_utc
from src.core.security.cookies import (
    browser_flow,
    clear_refresh_cookie,
    get_refresh_token,
    require_csrf,
    set_refresh_cookie,
)
from src.core.security.ratelimit import get_auth_limiter
from src.core.security.tokens import OpaqueToken
from src.db.session import get_db
from src.email import factory as email_factory
from src.email import templates
from src.models.workspace import User
from src.schemas.api import (
    ChangePasswordRequest,
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


async def _maybe_join_single_workspace(db: AsyncSession, container, user) -> None:
    if not settings.single_workspace:
        return
    await WorkspaceService(db, container.bus).join_single_workspace(user)


@router.get("/config")
async def auth_config() -> dict:
    """Public auth capabilities for the login UI (no secrets)."""
    return {
        "registration_enabled": settings.auth_allow_registration,
        "password_enabled": settings.auth_password_enabled,
        "oauth_enabled": bool(settings.oauth_provider_list),
        "providers": [
            {
                "id": p.get("id"),
                "display_name": p.get("display_name") or p.get("id"),
            }
            for p in settings.oauth_provider_list
            if p.get("id")
        ],
    }


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
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
    if not settings.auth_allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "registration is disabled")
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
        if msg == "registration is disabled":
            raise HTTPException(status.HTTP_403_FORBIDDEN, msg) from None
        # Map missing names to 422, else 409
        if "first_name and last_name" in msg:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg) from None
        raise HTTPException(status.HTTP_409_CONFLICT, msg) from None
    pair = await service.issue_tokens(
        user, ip_address=_client_ip(request), user_agent=_user_agent(request)
    )
    try:
        await _maybe_join_single_workspace(db, container, user)
    except Exception:
        logger.exception("failed to join single workspace for user %s", user.id)
    try:
        await _send_verification(service, user)
    except Exception:
        logger.exception("failed to send verification email for user %s", user.id)
    if browser_flow(request, body):
        set_refresh_cookie(response, pair.refresh_token, request=request)
        return TokenResponse(
            access_token=pair.access_token,
            refresh_token=None,
            token_type=pair.token_type,
            expires_in=pair.expires_in,
        )
    return TokenResponse(**pair.__dict__)


@router.post("/forgot-password", status_code=202)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> dict:
    # Always 202 — never reveal whether the email is registered.
    if not settings.auth_password_enabled:
        return {"detail": "if an account exists for this email, a reset link was sent"}
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
        if not settings.auth_password_enabled:
            raise AuthError("password login is disabled")
        await AuthService(db, container.bus).reset_password(
            body.token, body.new_password, ip_address=_client_ip(request)
        )
    except AuthError as exc:
        msg = str(exc)
        if msg == "password login is disabled":
            raise HTTPException(status.HTTP_403_FORBIDDEN, msg) from None
        raise HTTPException(status.HTTP_400_BAD_REQUEST, msg) from None
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
    response: Response,
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> TokenResponse:
    key = _limit_key(request, body.email)
    get_auth_limiter().check(key)
    if not settings.auth_password_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "password login is disabled")
    service = AuthService(db, container.bus)
    try:
        user = await service.login_password(
            body.email, body.password, ip_address=_client_ip(request)
        )
    except AuthError as exc:
        get_auth_limiter().fail(key)
        msg = str(exc)
        if msg in ("password login is disabled",):
            raise HTTPException(status.HTTP_403_FORBIDDEN, msg) from None
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, msg) from None
    get_auth_limiter().reset(key)
    try:
        await _maybe_join_single_workspace(db, container, user)
    except Exception:
        await db.rollback()
        logger.exception("failed to join single workspace for user %s", user.id)
    if user.totp_enabled:
        challenge = TwoFactorService(db, container.cipher, container.bus).issue_challenge(user.id)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"code": "2fa_required", "challenge_token": challenge},
        )
    pair = await service.issue_tokens(
        user, ip_address=_client_ip(request), user_agent=_user_agent(request)
    )
    if browser_flow(request, body):
        set_refresh_cookie(response, pair.refresh_token, request=request)
        return TokenResponse(
            access_token=pair.access_token,
            refresh_token=None,
            token_type=pair.token_type,
            expires_in=pair.expires_in,
        )
    return TokenResponse(**pair.__dict__)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> TokenResponse:
    cookie_token = get_refresh_token(request)
    raw = cookie_token or body.refresh_token
    if raw is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing refresh token")
    if cookie_token is not None:
        require_csrf(request)
    key = _limit_key(request, OpaqueToken.hash(raw))
    get_auth_limiter().check(key)
    service = AuthService(db, container.bus)
    try:
        pair = await service.rotate_refresh(
            raw,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except AuthError as exc:
        get_auth_limiter().fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    get_auth_limiter().reset(key)
    if settings.single_workspace:
        try:
            # pair.refresh_token is the NEW token; its owner is the rotated user.
            user = await service.get_user_by_refresh_token(pair.refresh_token)
            if user is not None:
                await _maybe_join_single_workspace(db, container, user)
        except Exception:
            await db.rollback()
            logger.exception("failed to join single workspace on refresh")
    if cookie_token is not None or browser_flow(request, body):
        set_refresh_cookie(response, pair.refresh_token, request=request)
        return TokenResponse(
            access_token=pair.access_token,
            refresh_token=None,
            token_type=pair.token_type,
            expires_in=pair.expires_in,
        )
    return TokenResponse(**pair.__dict__)


def _session_to_dict(row, *, current: bool) -> dict:
    return {
        "id": row.id,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "current": current,
    }


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> None:
    """Change password: current password always, 2FA code when TOTP is on.

    Revokes every session (including the current one) — the client must
    re-login with the new password. Mirrors the totp_disable password
    check and the 2fa/login code verification.

    The session stays valid when the submitted credentials are wrong, so a bad
    current password or 2FA code answers 400 — 401 is reserved for a dead
    session and would sign the caller out."""
    key = _limit_key(request, user.email)
    get_auth_limiter().check(key)
    service = AuthService(db, container.bus)
    try:
        await service.login_password(
            user.email, body.current_password, ip_address=_client_ip(request)
        )
    except AuthError as exc:
        get_auth_limiter().fail(key)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    get_auth_limiter().reset(key)
    if user.totp_enabled:
        if not body.code:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "two-factor code required")
        try:
            ok = await TwoFactorService(db, container.cipher, container.bus).verify_login_code(
                user, code=body.code
            )
        except TwoFactorError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
        if not ok:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid code")
    fresh = await db.get(type(user), user.id)
    await service.change_password(fresh or user, body.new_password, ip_address=_client_ip(request))


@router.get("/2fa/status")
async def totp_status(
    user: User = Depends(require_session_user),
):
    return {"enabled": bool(user.totp_enabled)}


@router.post("/2fa/setup")
async def totp_setup(
    user: User = Depends(require_session_user),
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
    user: User = Depends(require_session_user),
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
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> None:
    """Disable TOTP after confirming the current password.

    A wrong password answers 400, not 401: the session is alive, only the
    submitted password was wrong. 401 is reserved for a dead session and the
    web client would read it as one, force a logout, and lose the form."""
    key = _limit_key(request, user.email)
    get_auth_limiter().check(key)
    try:
        await AuthService(db, container.bus).login_password(
            user.email, body.password, ip_address=_client_ip(request)
        )
    except AuthError as exc:
        get_auth_limiter().fail(key)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    get_auth_limiter().reset(key)
    await TwoFactorService(db, container.cipher, container.bus).disable(user)


@router.post("/2fa/backup-codes")
async def totp_backup_codes(
    body: TwoFactorDisable,
    request: Request,
    user: User = Depends(require_session_user),
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
        # 400, not 401 — same reason as totp_disable: the session is alive.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
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
    response: Response,
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
    if browser_flow(request, body):
        set_refresh_cookie(response, pair.refresh_token, request=request)
        return TokenResponse(
            access_token=pair.access_token,
            refresh_token=None,
            token_type=pair.token_type,
            expires_in=pair.expires_in,
        )
    return TokenResponse(**pair.__dict__)


@router.get("/sessions", response_model=list[SessionRead])
async def list_sessions(
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    _: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    _ = container
    rows = await AuthService(db).list_sessions(principal.user.id)
    now = now_utc()
    return [
        _session_to_dict(r, current=(r.id == principal.session_id))
        for r in rows
        if r.revoked_at is None and ensure_utc(r.expires_at) >= now
    ]


@router.delete("/sessions", status_code=204)
async def revoke_all_sessions(
    request: Request,
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    _: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> None:
    await AuthService(db, container.bus).revoke_other_sessions(
        principal.user.id,
        current_session_id=principal.session_id,
        ip_address=_client_ip(request),
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    body: RefreshRequest = RefreshRequest(),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> None:
    """Revoke one refresh session. Cookie callers send an empty body (the
    refresh comes from the HttpOnly cookie); JSON clients must send
    ``{"refresh_token": ...}`` explicitly — an empty body 401s."""
    cookie_token = get_refresh_token(request)
    raw = cookie_token or body.refresh_token
    if raw is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing refresh token")
    if cookie_token is not None:
        require_csrf(request)
    await AuthService(db, container.bus).revoke_refresh(raw, ip_address=_client_ip(request))
    if cookie_token is not None:
        clear_refresh_cookie(response)


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    _: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> None:
    try:
        await AuthService(db, container.bus).revoke_session(
            principal.user.id,
            session_id,
            current_session_id=principal.session_id,
            ip_address=_client_ip(request),
        )
    except AuthError as exc:
        msg = str(exc)
        if msg == "cannot revoke the current session":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, msg) from None
        raise HTTPException(status.HTTP_404_NOT_FOUND, msg) from None


@router.get("/me")
async def me(
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    user = principal.user
    service = WorkspaceService(db)
    data = user_to_dict(user)
    # The principal's own deployment power, not the raw user column: an API
    # key is never a deployment admin, so a key holder never learns that the
    # user who minted it is one.
    data["is_superuser"] = principal.is_deployment_admin
    memberships = await service.list_workspaces(user.id)
    if principal.api_key is not None:
        # A key learns only its own workspace, never the creator's inventory:
        # every workspace listed here is one the key can actually reach.
        memberships = [m for m in memberships if m[0].id == principal.api_key.workspace_id]
    if settings.single_workspace:
        # Toggling onto an existing deployment: oldest wins, rest stay hidden.
        # (GET /workspaces still lists all memberships; /me is the UI surface.)
        single = await service.get_single_workspace()
        if single is not None:
            memberships = [m for m in memberships if m[0].id == single.id]
    data["workspaces"] = [
        workspace_to_dict(
            w, role=role.name, permissions=role.permissions, joined_at=member.created_at
        )
        for w, role, member in memberships
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
