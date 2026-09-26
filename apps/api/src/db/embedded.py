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


def _slug() -> str:
    # Imported lazily: src.settings resolves the default database URL through
    # src.db.embedded, so a top-level import here would be circular.
    from src.settings import settings

    return settings.app_slug


def data_dir() -> Path:
    override = os.environ.get("EMBEDDED_DB_DIR")
    if override:
        path = Path(override)
    else:
        path = Path.home() / ".local" / "share" / _slug() / "pgdata"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _kill_postmaster() -> None:
    """Force-stop the embedded server, bypassing pgserver's handle registry.

    pgserver's cleanup() refuses to stop the server while .handle_pids.json
    lists any process other than ours — and stale entries from killed runs
    wedge it forever. SIGINT (fast shutdown) directly at the postmaster,
    escalated to SIGKILL.
    """
    import signal

    import psutil  # ships with pgserver

    pid_file = data_dir() / "postmaster.pid"
    try:
        pid = int(pid_file.read_text().splitlines()[0].strip())
    except (OSError, ValueError):
        return
    try:
        proc = psutil.Process(pid)
        proc.send_signal(signal.SIGINT)  # fast shutdown
        try:
            proc.wait(timeout=10)
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except psutil.NoSuchProcess:
        pass


def _server_alive(uri: str) -> bool:
    """True when a fresh connection can actually run a query.

    pgserver treats a server as running while postmaster.pid names a live
    process, but a server whose /dev/shm segment was wiped (tmpfs cleanup,
    sandbox restart) still accepts sockets and then fails every backend
    startup with "could not open shared memory segment" — every connection
    errors until the process is restarted. Detect that so ensure_started
    can restart it instead of handing out a dead server forever.

    Runs on its own thread: callers resolve the URL both synchronously and
    from inside a running event loop (alembic async env), and asyncio.run
    refuses to nest — a worker thread always has a fresh loop.
    """
    import asyncio
    import threading

    import asyncpg

    ok = False

    def _run() -> None:
        nonlocal ok

        async def _ping() -> None:
            conn = await asyncpg.connect(uri, timeout=5)
            try:
                await conn.execute("SELECT 1")
            finally:
                await conn.close()

        try:
            asyncio.run(_ping())
            ok = True
        except Exception:
            ok = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=10)
    return ok


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
        if not _server_alive(_handle.get_uri()):
            logger.warning(
                "embedded postgres process is running but not accepting queries "
                "(stale shared memory) — restarting it"
            )
            _kill_postmaster()
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
