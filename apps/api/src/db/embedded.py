"""Embedded PostgreSQL for development (pgserver bundles real Postgres binaries).

No docker, no system postgres, no external services: the first access to the
database starts an embedded Postgres whose data lives in a local directory and
which shuts down automatically when the process exits.

Production overrides this by setting DATABASE_URL.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_handle = None
_lock = threading.Lock()
_started = False


def data_dir() -> Path:
    override = os.environ.get("EMBEDDED_DB_DIR")
    if override:
        path = Path(override)
    else:
        path = Path.home() / ".local" / "share" / "saas-template" / "pgdata"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_started():
    """Start (or reuse) the embedded postgres server. Idempotent and thread-safe."""
    global _handle, _started
    with _lock:
        if _started and _handle is not None:
            return _handle
        import pgserver

        logger.info("starting embedded postgres (pgdata=%s)", data_dir())
        _handle = pgserver.get_server(data_dir())
        _handle.ensure_postgres_running()
        _started = True
        logger.info("embedded postgres ready: %s", _handle.get_uri())
        return _handle


def embedded_uri() -> str:
    """Asyncpg-compatible connection URL for the embedded server."""
    uri = ensure_started().get_uri()
    if uri.startswith("postgresql://"):
        return uri.replace("postgresql://", "postgresql+asyncpg://", 1)
    return uri
