"""App-level handling of malformed ids in StringUUID columns.

Every primary key is a `StringUUID` (`src/db/base.py`), whose
`process_bind_param` calls `uuid.UUID(value)` while binding. A malformed id
from a path, query or body field therefore raises out of the bind processor
inside SQLAlchemy, before any route-level `except` clause can see it, and
surfaces as a 500.

The failure is identifiable without guessing: SQLAlchemy wraps it in
`StatementError` whose `orig` is the `ValueError` from `uuid.UUID`, and that
exception's message is the only place in the stack that names a bad id.
Business logic in `src/services/` also raises bare `ValueError` (see
`notifications.py`, `search_export.py`, `webhooks.py`), but never wrapped in
`StatementError`, so matching on the wrapper keeps those reporting as 500s.
Matching the message then distinguishes this failure from a genuine database
error that also surfaced as a `StatementError`.

Handling it here rather than per route keeps the guard in one place: the bind
happens inside `src/services/*.py`, below each route's `except` clauses, so a
route-level guard around the call cannot observe the exception.

`exc.params` is not used to confirm the value: it is `{'pk_1': ...}` for
`db.get` but `[{}]` for a `select().where(...)`, so the same failure has two
shapes depending on which query style reached it.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import StatementError

logger = logging.getLogger(__name__)

# The only ValueError `uuid.UUID` raises for a non-UUID input. Matched exactly so
# an unrelated ValueError that happens to be wrapped in a StatementError is not
# misreported as a 404.
_MALFORMED_UUID_MESSAGE = "badly formed hexadecimal UUID string"


def is_malformed_uuid_error(exc: StatementError) -> bool:
    """True only for a StringUUID bind failure caused by an unparseable id."""
    orig = getattr(exc, "orig", None)
    return isinstance(orig, ValueError) and str(orig) == _MALFORMED_UUID_MESSAGE


def register_malformed_id_handler(app: FastAPI) -> None:
    """Map a malformed StringUUID id to 404, leaving other DB errors as 500."""

    @app.exception_handler(StatementError)
    async def _handle_malformed_id(request: Request, exc: StatementError) -> JSONResponse:
        if not is_malformed_uuid_error(exc):
            raise exc
        logger.info("malformed id on %s %s -> 404", request.method, request.url.path)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "not found"})
