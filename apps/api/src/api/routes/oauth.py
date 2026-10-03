"""SSO login via any generic OIDC/OAuth2 provider.

Flow: GET /auth/oauth/{provider}/authorize → provider → GET
/auth/oauth/{provider}/callback?code&state → 302 to
{FRONTEND_URL}/oauth/callback?code=<one-time> → POST /auth/oauth/token.
Tokens never sit in URL logs; the one-time code is single-use, 5-minute TTL,
stored in the shared container cache.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_container
from src.api.routes.auth import (
    _client_ip,
    _join_single_workspace_best_effort,
    _user_agent,
)
from src.core.security.cookies import browser_flow, set_refresh_cookie
from src.core.security.ratelimit import get_auth_limiter
from src.db.session import get_db
from src.services.auth import AuthError, AuthService
from src.services.oauth import (
    CODE_TTL_HINT,
    OAuthError,
    build_authorize_url,
    claims_from_id_token,
    consume_state,
    exchange_code,
    fetch_userinfo,
    get_provider,
    normalize_identity,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/oauth", tags=["auth"])


class OAuthTokenRequest(BaseModel):
    code: str
    # Browser opt-in: set the HttpOnly refresh cookie and omit the refresh
    # token from the JSON body (in-memory access token only).
    use_cookies: bool = False


def _redirect_uri(request: Request, provider_id: str) -> str:
    """Absolute callback URL registered with the provider for this deployment."""
    return f"{request.base_url}api/v1/auth/oauth/{provider_id}/callback".rstrip("/")


def _frontend_callback(code: str) -> str:
    from src.settings import settings

    return f"{settings.frontend_url.rstrip('/')}/oauth/callback?code={code}"


ALLOWED_OAUTH_ERRORS = frozenset(
    {
        "missing code or state",
        "invalid or expired state",
        "sign-in failed",
        "registration is disabled",
    }
)


def _error_redirect(detail: str) -> RedirectResponse:
    from src.settings import settings

    base = settings.frontend_url.rstrip("/")
    safe = detail if detail in ALLOWED_OAUTH_ERRORS else "sign-in failed"
    return RedirectResponse(f"{base}/login?error={safe}", status_code=302)


@router.get("/{provider_id}/authorize")
async def oauth_authorize(provider_id: str, request: Request):
    from src.services.oauth import _discovery

    get_auth_limiter().check(f"oauth:{_client_ip(request) or 'unknown'}:{provider_id}")
    container = get_container(request)
    try:
        provider = get_provider(provider_id)
    except OAuthError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    try:
        doc = await _discovery(provider, container.cache)
        url = build_authorize_url(
            provider, doc, container.cache, _redirect_uri(request, provider_id)
        )
    except OAuthError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    return RedirectResponse(url, status_code=302)


@router.get("/{provider_id}/callback")
async def oauth_callback(
    provider_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    get_auth_limiter().check(f"oauth:{_client_ip(request) or 'unknown'}:{provider_id}")
    container = get_container(request)
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return _error_redirect("missing code or state")
    try:
        saved = consume_state(container.cache, state)
    except OAuthError:
        return _error_redirect("invalid or expired state")
    if saved.get("provider") != provider_id:
        return _error_redirect("invalid or expired state")
    redirect_uri = saved.get("redirect_uri") or _redirect_uri(request, provider_id)
    try:
        provider = get_provider(provider_id)
        from src.services.oauth import _discovery

        doc = await _discovery(provider, container.cache)
        tokens = await exchange_code(provider, doc, code=code, redirect_uri=redirect_uri)
        claims = None
        if tokens.get("id_token"):
            claims = await claims_from_id_token(provider, doc, tokens["id_token"], container.cache)
        userinfo = {}
        if tokens.get("access_token"):
            userinfo = await fetch_userinfo(provider, doc, tokens["access_token"])
        identity = normalize_identity(provider_id=provider_id, claims=claims, userinfo=userinfo)
    except OAuthError as exc:
        logger.warning("oauth callback failed provider=%s: %s", provider_id, exc)
        return _error_redirect("sign-in failed")
    service = AuthService(db, container.bus)
    try:
        user = await service.upsert_oauth_user(
            provider=identity["provider"],
            subject=identity["subject"],
            email=identity["email"],
            display_name=identity["display_name"],
            first_name=identity["first_name"],
            last_name=identity["last_name"],
        )
    except AuthError as exc:
        logger.info("oauth signup rejected provider=%s: %s", provider_id, exc)
        return _error_redirect("registration is disabled")
    if user.totp_enabled:
        # Passwordless SSO still honors 2FA: park the user id behind the
        # one-time code and let the frontend complete the challenge.
        one_time = secrets.token_urlsafe(32)
        container.cache.set(
            CODE_TTL_HINT + one_time,
            {"type": "2fa", "user_id": user.id},
        )
        return RedirectResponse(_frontend_callback(one_time), status_code=302)
    try:
        pair = await service.issue_tokens(
            user, ip_address=_client_ip(request), user_agent=_user_agent(request)
        )
    except Exception:
        logger.exception("oauth token issue failed user=%s", user.id)
        return _error_redirect("sign-in failed")
    # A failed join stays log-only: the 302 must happen either way.
    await _join_single_workspace_best_effort(db, container, user)
    one_time = secrets.token_urlsafe(32)
    container.cache.set(
        CODE_TTL_HINT + one_time,
        {"type": "tokens", "access_token": pair.access_token, "refresh_token": pair.refresh_token},
    )
    return RedirectResponse(_frontend_callback(one_time), status_code=302)


@router.post("/token")
async def oauth_token(
    body: OAuthTokenRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    get_auth_limiter().check(f"oauth:{_client_ip(request) or 'unknown'}:token")
    container = get_container(request)
    entry = container.cache.get(CODE_TTL_HINT + body.code)
    if entry is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired code")
    container.cache.delete(CODE_TTL_HINT + body.code)
    if not isinstance(entry, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired code")
    if entry.get("type") == "2fa":
        from src.services.two_factor import TwoFactorService

        challenge = TwoFactorService(
            db,
            container.cipher,
            container.bus,
        ).issue_challenge(entry["user_id"])
        return {"challenge_token": challenge, "two_factor_required": True}
    if browser_flow(request, body):
        # The callback parked a minted refresh token in the cache entry; move
        # it into the HttpOnly cookie so JS only ever sees the access token.
        if entry.get("refresh_token"):
            set_refresh_cookie(response, entry["refresh_token"], request=request)
        return {
            "access_token": entry.get("access_token"),
            "token_type": "Bearer",
        }
    return {
        "access_token": entry.get("access_token"),
        "refresh_token": entry.get("refresh_token"),
        "token_type": "Bearer",
    }
