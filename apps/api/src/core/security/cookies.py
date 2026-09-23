"""HttpOnly refresh-cookie helpers — the single place cookie flags live.

Browser session flow: the refresh token is stored in this cookie (JS can
never read it); the short-lived access JWT stays in frontend memory.
Non-browser clients keep the JSON token bodies. OAuth/2FA endpoints must
reuse these helpers instead of reimplementing flags.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, Response, status

from src.settings import settings

CSRF_HEADER = "X-Requested-With"
CSRF_HEADER_VALUE = "XMLHttpRequest"


def set_refresh_cookie(response: Response, token: str) -> None:
    kwargs: dict = {
        "key": settings.refresh_cookie_name,
        "value": token,
        "httponly": True,
        "secure": settings.refresh_cookie_secure_effective,
        "samesite": "lax",
        "path": settings.refresh_cookie_path,
        "max_age": settings.refresh_token_expire_days * 24 * 3600,
    }
    if settings.refresh_cookie_domain:
        kwargs["domain"] = settings.refresh_cookie_domain
    response.set_cookie(**kwargs)


def clear_refresh_cookie(response: Response) -> None:
    kwargs: dict = {
        "key": settings.refresh_cookie_name,
        "path": settings.refresh_cookie_path,
    }
    if settings.refresh_cookie_domain:
        kwargs["domain"] = settings.refresh_cookie_domain
    response.delete_cookie(**kwargs)


def get_refresh_token(request: Request) -> str | None:
    return request.cookies.get(settings.refresh_cookie_name)


def browser_flow(request: Request, body: object | None = None) -> bool:
    """True when the caller opted into the cookie session flow.

    Explicit opt-in (JSON flag or query param) — not cookie presence — so a
    non-browser client that happens to forward cookies can never silently
    lose its JSON refresh token.
    """
    if body is not None and isinstance(body, dict) and body.get("use_cookies") is True:
        return True
    use_cookies = getattr(body, "use_cookies", None)
    if use_cookies is True:
        return True
    if request.query_params.get("use_cookies") == "true":
        return True
    return request.headers.get("X-Session-Flow") == "cookie"


def require_csrf(request: Request) -> None:
    """Reject cross-site forged cookie requests on cookie-authenticated endpoints."""
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    allowed = set(settings.cors_origin_list)
    if origin is not None:
        if origin.rstrip("/") not in {o.rstrip("/") for o in allowed}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "cross-origin request rejected")
    elif referer is not None:
        allowed_ref = any(
            referer.startswith(o.rstrip("/") + "/") or referer.rstrip("/") == o.rstrip("/")
            for o in allowed
        )
        if not allowed_ref:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "cross-origin request rejected")
    if request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing CSRF header")
