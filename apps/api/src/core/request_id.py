"""Per-request ID: accept, mint, propagate, echo.

One stdlib middleware. Reads `X-Request-ID` when the caller sends one,
otherwise mints a 16-hex-char id. The id lives on `request.state` and in a
ContextVar (so job/executor/dispatcher log lines can include it), is echoed
back on the response, and anchors one INFO log line per request.
"""

from __future__ import annotations

import contextvars
import logging
import re
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_VALID_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _coerce_request_id(incoming: str | None) -> str:
    """Echo the caller's id only if header/quote/newline-safe; else mint one."""
    if incoming and _VALID_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex[:16]


def get_request_id() -> str:
    """Current request's id, or "-" outside a request."""
    return _request_id.get()


def _route_template(request: Request) -> str:
    """Full path with path-param values replaced by `{name}`.

    Built from url.path (which keeps the router prefix that
    `scope["route"].path` drops) so cardinality stays bounded without
    losing the prefix.
    """
    template = request.url.path
    for name, value in (request.scope.get("path_params") or {}).items():
        template = template.replace(f"/{value}", f"/{{{name}}}", 1)
    return template


class RequestIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        request_id = _coerce_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        token = _request_id.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            _request_id.reset(token)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response.headers[REQUEST_ID_HEADER] = request_id
        from src.core.metrics import observe_request

        observe_request(
            method=request.method,
            path=_route_template(request),
            status=response.status_code,
        )
        logger.info(
            "rid=%s %s %s -> %s %sms",
            request_id,
            request.method,
            _route_template(request),
            response.status_code,
            elapsed_ms,
        )
        return response
