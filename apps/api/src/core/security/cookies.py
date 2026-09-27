"""HttpOnly refresh-cookie helpers — the single place cookie flags live.

Browser session flow: the refresh token is stored in this cookie (JS can
never read it); the short-lived access JWT stays in frontend memory.
Non-browser clients keep the JSON token bodies. OAuth/2FA endpoints must
reuse these helpers instead of reimplementing flags.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response, status

from src.settings import settings

CSRF_HEADER = "X-Requested-With"
CSRF_HEADER_VALUE = "XMLHttpRequest"


def _is_https_request(request: Request | None) -> bool:
    """True when the request arrived over TLS (proxy-aware).

    Uvicorn runs with --proxy-headers in prod (infra/docker/docker-compose.prod.yml:71),
    so request.url.scheme already honors X-Forwarded-Proto; the explicit header
    check covers test clients and servers without proxy-header handling. Port
    suffix (:443) covers X-Forwarded-Host forms that carry no scheme, for a
    proxy that forwards the host only.

    The header reads are client-controlled and deliberately ignore uvicorn's
    forwarded_allow_ips (prod sets --forwarded-allow-ips='*', so there is no
    trusted boundary to check). They are fail-secure: they can only return
    True, never strip Secure from a real https request. Narrowing
    forwarded_allow_ips must come with a re-check of this function."""
    if request is None:
        return False
    if request.url.scheme == "https":
        return True
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if proto == "https":
        return True
    host = request.headers.get("x-forwarded-host", "") or request.headers.get("host", "")
    return host.strip().lower().endswith(":443")


def cookie_secure_for(request: Request | None = None) -> bool:
    """Secure flag for the refresh cookie.

    Explicit REFRESH_COOKIE_SECURE wins; otherwise https requests get Secure
    even when ENVIRONMENT says development (e.g. prod misconfig serving TLS
    behind a plain-http app server), and plain-http requests skip it so the
    cookie still stores."""
    if settings.refresh_cookie_secure is not None:
        return settings.refresh_cookie_secure
    if _is_https_request(request):
        return True
    return settings.refresh_cookie_secure_effective


def set_refresh_cookie(response: Response, token: str, request: Request) -> None:
    """Set the refresh cookie. `request` is required: the Secure flag is derived
    from it, and a default would silently restore the ENVIRONMENT-based flag."""
    kwargs: dict = {
        "key": settings.refresh_cookie_name,
        "value": token,
        "httponly": True,
        "secure": cookie_secure_for(request),
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


def _origin_allowed(url: str) -> bool:
    """True when an Origin (or Referer) URL is covered by CORS_ORIGINS.

    Same rules as the CORS middleware: the exact entries plus the regex built
    from the `*` entries, so a wildcard origin is not rejected as cross-site."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return False
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin in {o.rstrip("/") for o in settings.cors_origin_list}:
        return True
    pattern = settings.cors_origin_regex
    return bool(pattern) and re.fullmatch(pattern, origin) is not None


def require_csrf(request: Request) -> None:
    """Reject cross-site forged cookie requests on cookie-authenticated endpoints."""
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    if origin is not None:
        allowed = _origin_allowed(origin)
    elif referer is not None:
        allowed = _origin_allowed(referer)
    else:
        allowed = True
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cross-origin request rejected")
    if request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing CSRF header")
