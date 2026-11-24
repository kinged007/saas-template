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
from src.core.security.ratelimit import get_auth_limiter, get_mail_limiter, get_register_limiter
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
from src.services.serializers import (
    profile_to_dict,
    session_to_dict,
    user_to_dict,
    workspace_to_dict,
)
from src.services.two_factor import TwoFactorError, TwoFactorService
from src.services.workspaces import WorkspaceService
from src.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# One string for both places that refuse a session for an account that is
# gone: the client's message contract depends on them being identical.
ACCOUNT_GONE_DETAIL = "account no longer exists"


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


def _mail_limit_key(request: Request) -> str:
    """IP-only key for the coarse mail-volume backstop (#1346)."""
    return f"mailip:{_client_ip(request) or 'unknown'}"


def _account_limit_key(email: str | None = None) -> str:
    """Account-scoped limiter key: one inbox attacked from many addresses
    shares one budget even when every request carries a different IP."""
    return f"account:{(email or '').lower()}"


async def _maybe_join_single_workspace(db: AsyncSession, container, user) -> None:
    if not settings.single_workspace:
        return
    await WorkspaceService(db, container.bus).join_single_workspace(user)


async def _join_single_workspace_best_effort(db: AsyncSession, container, user) -> User:
    """Join the single workspace; on failure log, roll back, return a usable user.

    A failed join does not fail authentication: the caller gets a valid session
    with no membership, and every workspace-scoped route still 403s without one.
    The rollback expires every loaded instance, so the user is re-read instead
    of being handed back needing a lazy refresh. An empty re-read drops the
    session rather than authenticating a detached row.
    """
    user_id = user.id
    try:
        await _maybe_join_single_workspace(db, container, user)
    except Exception:
        logger.exception("failed to join single workspace for user %s", user_id)
        await db.rollback()
        fresh = await AuthService(db).get_user(user_id)
        if fresh is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, ACCOUNT_GONE_DETAIL) from None
        return fresh
    return user


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
    # IP-wide mail backstop (#1346): 429 before any DB write; only the
    # verification send below spends it, so a 409 duplicate spends nothing.
    mail_key = _mail_limit_key(request)
    get_mail_limiter().check(mail_key)
    # The verification mail needs a cap no per-(IP, email) key can dodge
    # (#1343): the registrant owns every fresh address, so the key is the IP
    # alone, spent out of the register limiter's own window — not the auth
    # limiter's (IP, email) budget.
    register_key = _limit_key(request)
    get_register_limiter().check(register_key)
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
    user = await _join_single_workspace_best_effort(db, container, user)
    try:
        await _send_verification(service, user)
    except Exception:
        logger.exception("failed to send verification email for user %s", user.id)
    # The send (or its attempt) is the metered event for the IP-wide mail
    # backstop (#1346).
    get_mail_limiter().fail(mail_key)
    # Every send spends one unit of the register limiter's budget, which the
    # window caps: like forgot-password there is no success reset, because the
    # send (or its attempt) is the metered event, not a failure.
    get_register_limiter().fail(register_key)
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
    key = _limit_key(request, str(body.email))
    get_auth_limiter().check(key)
    mail_key = _mail_limit_key(request)
    get_mail_limiter().check(mail_key)
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
    # Every call spends one unit of the auth-limiter budget — known and
    # unknown addresses alike, so a 429 never reveals whether the email is
    # registered. Like resend-verification there is no success reset: the
    # send (or its attempt) is the metered event, not a failure.
    get_auth_limiter().fail(key)
    get_mail_limiter().fail(mail_key)
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
    request: Request,
    # Key-reachable by design; rate-limited per (IP, email) — see #1289 and
    # `require_session_user`'s docstring.
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> dict:
    key = _limit_key(request, user.email)
    get_auth_limiter().check(key)
    mail_key = _mail_limit_key(request)
    get_mail_limiter().check(mail_key)
    if getattr(user, "email_verified_at", None) is not None:
        return {"detail": "email already verified"}
    service = AuthService(db, container.bus)
    fresh = await db.get(type(user), user.id)
    try:
        await _send_verification(service, fresh or user)
    except Exception:
        logger.exception("failed to resend verification email for user %s", user.id)
    # Every send spends one unit of the auth-limiter budget, which the window
    # caps: unlike login there is no success reset, because the send itself
    # is the metered event, not a failure. The send also spends the IP-wide
    # mail backstop (#1346).
    get_auth_limiter().fail(key)
    get_mail_limiter().fail(mail_key)
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
    account_key = _account_limit_key(body.email)
    limiter = get_auth_limiter()
    limiter.check(key)
    # Distributed guessing: one inbox attacked from many addresses is still
    # one account, so it shares one budget on top of the per-IP one.
    limiter.check(account_key)
    if not settings.auth_password_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "password login is disabled")
    service = AuthService(db, container.bus)
    try:
        user = await service.login_password(
            body.email, body.password, ip_address=_client_ip(request)
        )
    except AuthError as exc:
        limiter.fail(key)
        limiter.fail(account_key)
        msg = str(exc)
        if msg in ("password login is disabled",):
            raise HTTPException(status.HTTP_403_FORBIDDEN, msg) from None
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, msg) from None
    # Captured before the try: the helper's rollback expires the instance,
    # so reading attributes in the handler would lazy-load.
    user_id = user.id
    try:
        # The only HTTPException in here is the helper's account-gone guard, so
        # charging the limiter for it is always a 401 charge, nothing else.
        # Below the reset because this key is ip:email and stays reusable, so a
        # charge on it can actually throttle the caller.
        user = await _join_single_workspace_best_effort(db, container, user)
    except HTTPException:
        # Error, not exception: the helper logged the fault with a traceback
        # already; this is the login-level correlation (parity with the
        # refresh flow's #714 fix).
        logger.error("account gone on login (user %s)", user_id)
        limiter.fail(key)
        limiter.fail(account_key)
        raise
    limiter.reset(key)
    limiter.reset(account_key)
    if user.totp_enabled:
        # Deliberately uncharged, unlike the 401s above: the password was
        # right and the caller still owes the second factor. The guesses that
        # do matter are a rejected code, charged on ip:<user_id> rather than
        # this key. See the rule in src/core/security/ratelimit.py.
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
    # The rotation above is already committed, so a raise here does not unwind
    # it: the new refresh token is dropped on the floor and never reaches the
    # client. pair.refresh_token is the NEW token, and the account can be
    # deleted in the window between rotate_refresh's two commits, so the owner
    # is re-read before any pair is handed out. Fails closed: a re-read that
    # raises must not fall through to set_refresh_cookie.
    user = await service.get_user_by_refresh_token(pair.refresh_token)
    if user is None:
        get_auth_limiter().fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, ACCOUNT_GONE_DETAIL)
    if settings.single_workspace:
        # Captured before the try: the helper's rollback expires the instance,
        # so reading attributes in the handler would lazy-load.
        user_id = user.id
        try:
            # The only HTTPException in here is the helper's account-gone
            # guard, so this charge is always a 401 charge, nothing else.
            await _join_single_workspace_best_effort(db, container, user)
        except HTTPException:
            # Error, not exception: the helper logged the fault with a
            # traceback already; this is the refresh-level correlation (#714).
            logger.error("account gone on refresh (user %s)", user_id)
            get_auth_limiter().fail(key)
            raise
        except Exception:
            # Best-effort, like the helper itself: no rollback of its own here
            # (it already rolled back before re-reading the user), and nothing
            # after this may lazy-load user.*.
            logger.exception("failed to join single workspace on refresh")
    # Reset only once the request is authenticated: the account-gone 401s
    # charge the limiter instead of clearing its window.
    get_auth_limiter().reset(key)
    if cookie_token is not None or browser_flow(request, body):
        set_refresh_cookie(response, pair.refresh_token, request=request)
        return TokenResponse(
            access_token=pair.access_token,
            refresh_token=None,
            token_type=pair.token_type,
            expires_in=pair.expires_in,
        )
    return TokenResponse(**pair.__dict__)


def _require_session_user(principal: AuthPrincipal) -> None:
    """Session routes are a user-session concept; API keys carry no session."""
    if principal.api_key is not None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "session management is not available to API keys"
        )


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
    # The challenge survives a wrong code so the user can retry with the same
    # token: peek first, consume only once the code verifies. The rate limiter
    # runs before verification, so guessing a code is throttled on ip:<user_id>.
    try:
        user_id = svc.peek_challenge(body.challenge_token)
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
    try:
        svc.consume_challenge(body.challenge_token)
    except TwoFactorError as exc:
        # A concurrent request spent the single-use challenge first.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
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
        session_to_dict(r, current=(r.id == principal.session_id))
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
        revoke_reason="user",
        actor_user_id=principal.user.id,
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
        # every workspace listed here is one the key can actually reach. A key
        # is pinned to that one workspace and its gate never reads the flag, so
        # the single-workspace filter does not apply to it.
        memberships = [m for m in memberships if m[0].id == principal.api_key.workspace_id]
    elif settings.single_workspace:
        # Toggling onto an existing deployment: oldest wins, rest stay hidden.
        # (GET /workspaces still lists all memberships; /me is the UI surface.)
        single = await service.get_single_workspace()
        if single is not None:
            memberships = [m for m in memberships if m[0].id == single.id]
    # `permissions` always means what this principal can do here: a session
    # user gets the union of the roles it holds in the listed workspaces, an
    # API key only its own grant — in the top-level field and in each nested
    # entry alike. Each entry still names the creator's membership role (the
    # fact `require_session_user` relies on); only the permission lists are
    # the key's own. Branch on `is not None`, never on truthiness — an empty
    # grant is a real grant, not a missing one. Empty too when the creator's
    # membership in the key's workspace is not active: `list_workspaces`
    # drops those rows and the gate refuses them, so the two must not disagree.
    if principal.api_key is not None:
        # Same discipline as the session branch below: the stored order, deduped
        # — not a re-sort. `services/api_keys.py` is the only writer of the
        # column and stores `sorted(...)` there, so a key minted through the
        # API reads back alphabetically and this changes nothing for it.
        key_grant = list(dict.fromkeys(principal.api_key.permissions)) if memberships else []
        data["workspaces"] = [
            workspace_to_dict(w, role=role.name, permissions=key_grant, joined_at=m.created_at)
            for w, role, m in memberships
        ]
        data["permissions"] = key_grant
    else:
        data["workspaces"] = [
            workspace_to_dict(
                w, role=role.name, permissions=role.permissions, joined_at=member.created_at
            )
            for w, role, member in memberships
        ]
        # Ordered dedup, not a sort: the union keeps each role's registry
        # order (first occurrence wins across memberships), matching the
        # nested entries which carry role.permissions verbatim.
        data["permissions"] = list(
            dict.fromkeys(p for _, role, _ in memberships for p in role.permissions)
        )
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
