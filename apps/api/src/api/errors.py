"""App-level handling of malformed ids in StringUUID columns.

Every primary key (and every id-shaped FK column) is a `StringUUID`
(`src/db/base.py`), whose `process_bind_param` calls `uuid.UUID(value)` while
binding. A malformed id from a path, query or body field therefore raises out of
the bind processor inside SQLAlchemy, before any route-level `except` clause can
see it, and surfaces as a 500.

The failure is identifiable without guessing: `StringUUID` raises
`MalformedUUIDError`, SQLAlchemy wraps it in a `StatementError` whose `orig` is
that exception, and no other code raises it. Business logic in `src/services/`
raises bare `ValueError`s (see `notifications.py`, `search_export.py`,
`webhooks.py`) and a real database failure surfaces as a `StatementError` whose
`orig` is a driver error, so both keep reporting as 500s.

Handling it here rather than per route keeps the guard in one place: the bind
happens inside `src/services/*.py`, below each route's `except` clauses, so a
route-level guard around the call cannot observe the exception.

`exc.params` is not used to confirm the value: it is `{'pk_1': ...}` for
`db.get` but `[{}]` for a `select().where(...)`, so the same failure has two
shapes depending on which query style reached it.

Body-sourced ids are validated by pydantic (`UUID` in `schemas/api.py`) and so
never reach this handler. 404 is the status for a path or query id, which
addresses a resource; a malformed value on a write path is a bad request and
belongs to its schema's validation. ponytail: add a bad-request branch per
write field when a write route starts binding an unvalidated id.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import StatementError

from src.db.base import MalformedUUIDError

logger = logging.getLogger(__name__)


def is_malformed_uuid_error(exc: StatementError) -> bool:
    """True only for a StringUUID bind failure caused by an unparseable id."""
    return isinstance(getattr(exc, "orig", None), MalformedUUIDError)


def register_malformed_id_handler(app: FastAPI) -> None:
    """Map a malformed StringUUID id to 404, leaving other DB errors as 500."""

    @app.exception_handler(StatementError)
    async def _handle_malformed_id(request: Request, exc: StatementError) -> JSONResponse:
        if not is_malformed_uuid_error(exc):
            raise exc
        # debug: the id is attacker-controlled, so this path is a log-volume risk
        # on an unauthenticated-reachable route. The 404 already carries the
        # signal, so nothing about the raw path is logged.
        logger.debug("malformed id on %s -> 404", request.method)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "not found"})
