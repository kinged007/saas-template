from __future__ import annotations

import asyncio  # noqa: E402
import inspect  # noqa: E402
import os  # noqa: E402
from datetime import timedelta  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

_TEST_DB_NAME = "test_saas_template.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///./{_TEST_DB_NAME}"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["FERNET_KEYS"] = "test-fernet-key-value"
os.environ["EVENT_BUS_DRIVER"] = "inprocess"
os.environ["ENVIRONMENT"] = "test"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ["SUPERADMIN_EMAIL"] = "root@example.com"

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from src import models as _models  # noqa: E402,F401  (register tables on Base.metadata)
from src.core.security.ratelimit import get_register_limiter  # noqa: E402
from src.db.base import Base  # noqa: E402
from src.db.session import engine  # noqa: E402
from src.settings import settings  # noqa: E402

if TYPE_CHECKING:  # noqa: E402
    from src.models.jobs import JobRun


def _db_path() -> Path:
    """Filesystem path of the sqlite file the suite shares.

    sqlite resolves a relative URL against the cwd, so the unlink must use the
    same path the engine opens. The name is pinned to the suite's scratch file:
    if DATABASE_URL is ever pointed at a real database, this fails loudly here
    instead of silently deleting it.
    """
    url = make_url(settings.resolved_database_url)
    assert url.get_backend_name() == "sqlite", f"expected a sqlite test database, got {url}"
    path = Path(url.database or "")
    assert path.name == _TEST_DB_NAME, f"refusing to unlink {path}"
    return path


async def _discard_db_file() -> None:
    """Take the sqlite file away from every connection that is still open."""
    await engine.dispose()  # close this suite's pooled connections first
    path = _db_path()
    path.unlink(missing_ok=True)
    for suffix in ("-journal", "-wal", "-shm"):  # sidecars outlive the db file
        path.with_name(path.name + suffix).unlink(missing_ok=True)


async def _fresh_db() -> None:
    """Hand the test a database no other connection can be looking at.

    # ponytail: unlink rather than drop_all, so a background bus worker or job
    # task still draining at the end of a test keeps its lock and its stale
    # read snapshot on an inode nobody else can open. Ceiling: POSIX-only (a
    # Windows box cannot unlink a file sqlite has open). Upgrade path: a
    # per-test path plus rebinding `engine`, which needs the >=8 src modules
    # that bind `SessionFactory` by name at import.
    """
    await _discard_db_file()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(autouse=True)
async def _clean_db():
    await _fresh_db()
    yield
    await _discard_db_file()


@pytest.fixture(autouse=True)
def _pin_refresh_cookie_secure(monkeypatch):
    """Start every test from the unset-cookie-flag state.

    Settings loads .env / ~/.config/saas-template/.env at import time, so an
    ambient REFRESH_COOKIE_SECURE short-circuits the first clause of
    cookie_secure_for() and cookie-secure assertions fail for reasons the
    tests do not assert (#524). Tests wanting an explicit value monkeypatch
    it on top of this pin.
    """
    monkeypatch.setattr(settings, "refresh_cookie_secure", None)

@pytest.fixture
async def app():
    from src.main import app as fastapi_app

    # /auth/register meters mail per IP on the register limiter; spent keys are
    # process-wide, so a test's registrations must not throttle the next test's
    # register_user setup (#1343).
    get_register_limiter().clear()
    async with LifespanManager(fastapi_app):
        yield fastapi_app


@pytest.fixture
async def app_client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def register_user(
    client: AsyncClient,
    email: str = "user@example.com",
    first_name: str = "Test",
    last_name: str = "User",
) -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Password123!",
            "first_name": first_name,
            "last_name": last_name,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def register_user_with_names(
    client: AsyncClient, email: str, first_name: str, last_name: str
) -> dict:
    return await register_user(client, email=email, first_name=first_name, last_name=last_name)


async def login(client: AsyncClient, email: str = "user@example.com") -> dict:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password123!"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def auth_headers(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def break_single_workspace_join(client: AsyncClient, email: str = "first@example.com") -> str:
    """Leave the single workspace with only its owner role, so an auto-join raises.

    Returns the workspace id. The failure is real (no monkeypatch), which
    matters: a fake failure raises before the join opened a transaction, so the
    rollback that follows has nothing to expire.
    """
    from sqlalchemy import delete

    from src.db.session import SessionFactory
    from src.models.workspace import Role

    tokens = await register_user(client, email)
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    ws_id = me.json()["workspaces"][0]["id"]
    async with SessionFactory() as session:
        await session.execute(delete(Role).where(Role.workspace_id == ws_id, Role.name != "owner"))
        await session.commit()
    return ws_id


async def create_workspace(client: AsyncClient, tokens: dict, name: str = "Acme Corp") -> dict:
    resp = await client.post(
        "/api/v1/workspaces",
        json={"name": name},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def ws_headers(tokens: dict, workspace_id: str) -> dict:
    headers = auth_headers(tokens)
    headers["X-Workspace-ID"] = workspace_id
    return headers


async def expire_invitation(invitation_id: str) -> None:
    """Backdate an invitation's expiry for expired-invite test paths.

    The assert pins the helper's preconditions: a stale id must fail the
    calling test naming the row, and the row must still carry an expiry (the
    column is NOT NULL, so a NULL here means the fixture wrote something else).
    """
    from datetime import timedelta

    from src.core.dates import now_utc
    from src.db.session import SessionFactory
    from src.models.core import Invitation

    async with SessionFactory() as session:
        row = await session.get(Invitation, invitation_id)
        assert row is not None and row.expires_at is not None, invitation_id
        row.expires_at = now_utc() - timedelta(minutes=5)
        await session.commit()


async def run_job_via_scheduler(
    key: str,
    *,
    workspace_id: str | None = None,
    missed_by: timedelta = timedelta(hours=3),
    timeout_s: float = 10.0,
) -> tuple[JobRun, list[str]]:
    """Drive a job through the real scheduler -> bus -> executor path.

    Backdates the provisioned definition's `next_run_at` so a tick claims it as
    a missed occurrence, then waits for the durable worker to finish the run.
    Ticks the production `app.state.job_scheduler` built in `main.py`, so the
    container -> scheduler wiring is under test too. Returns the run plus its
    captured log messages.

    A tick also runs housekeeping when due: `_last_housekeeping` starts at 0.0
    while being compared against `loop.time()`, so on a host up longer than
    HOUSEKEEPING_INTERVAL_SECONDS (1h) the first tick additionally runs
    `fail_stale_runs` + `prune_history` across other jobs' run rows.
    """
    from sqlalchemy import select

    from src.core.dates import now_utc
    from src.db.session import SessionFactory
    from src.main import app as fastapi_app
    from src.models.jobs import JobDefinition, JobLogEntry, JobRun

    async with SessionFactory() as session:
        scope = (
            JobDefinition.workspace_id == workspace_id
            if workspace_id is not None
            else JobDefinition.workspace_id.is_(None)
        )
        definition = (
            await session.execute(select(JobDefinition).where(JobDefinition.key == key, scope))
        ).scalar_one()
        definition.next_run_at = now_utc() - missed_by
        definition_id = definition.id
        await session.commit()

    scheduled = await fastapi_app.state.job_scheduler.tick()

    for _ in range(int(timeout_s * 10)):
        async with SessionFactory() as session:
            run = (
                (
                    await session.execute(
                        select(JobRun)
                        .where(JobRun.definition_id == definition_id)
                        .order_by(JobRun.created_at.desc())
                    )
                )
                .scalars()
                .first()
            )
            if run is not None and run.status in ("success", "failed", "timed_out"):
                messages = (
                    (
                        await session.execute(
                            select(JobLogEntry.message)
                            .where(JobLogEntry.run_id == run.id)
                            .order_by(JobLogEntry.seq)
                        )
                    )
                    .scalars()
                    .all()
                )
                return run, list(messages)
        await asyncio.sleep(0.1)
    raise AssertionError(f"job {key} did not finish within {timeout_s}s (scheduled={scheduled})")


async def wait_for(predicate, timeout_secs: float = 3.0, interval: float = 0.02) -> bool:
    """Poll `predicate` until it returns truthy; False once the deadline passes.

    `predicate` may be sync or async. Timeout reports False instead of raising so
    every call site keeps its own failure message.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_secs
    while loop.time() < deadline:
        result = predicate()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return True
        await asyncio.sleep(interval)
    return False
