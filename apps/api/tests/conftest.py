from __future__ import annotations

import asyncio  # noqa: E402
import inspect  # noqa: E402
import os  # noqa: E402
from datetime import timedelta  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

# Only selects the sqlite branch of settings.resolved_database_url. The module-level
# engine built from it is never connected to — the autouse fixture below rebinds it
# per test — so no file is created at this path.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["FERNET_KEYS"] = "test-fernet-key-value"
os.environ["EVENT_BUS_DRIVER"] = "inprocess"
os.environ["ENVIRONMENT"] = "test"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ["SUPERADMIN_EMAIL"] = "root@example.com"

import pytest  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from src import models as _models  # noqa: E402,F401  (register tables on Base.metadata)
from src.core.security.ratelimit import get_register_limiter  # noqa: E402
from src.db import session as session_module  # noqa: E402
from src.db.base import Base  # noqa: E402
from src.db.session import SessionFactory  # noqa: E402

if TYPE_CHECKING:  # noqa: E402
    from src.models.jobs import JobRun


@pytest.fixture(autouse=True)
async def _clean_db(tmp_path):
    """Give every test its own SQLite file, rebound over the shared SessionFactory.

    One file for the whole session plus a drop_all between tests made full-suite runs
    fail spuriously: a background event-bus worker still draining its last transaction
    could hold the file lock when the drop ran. A fresh file per test removes the
    shared state and the contention at once — a late writer only ever touches a
    database nobody reads again.

    `SessionFactory.configure` reaches every `src` consumer (all modules importing it
    hold the same object); the module-attribute rebind is what `tests/test_ws_auth.py`
    reads. `timeout` matches src/db/session.py: busy-wait on the write lock, no WAL.
    """
    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/test.db", connect_args={"timeout": 30}
    )
    session_module.engine = test_engine
    SessionFactory.configure(bind=test_engine)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield
    finally:
        await test_engine.dispose()


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


async def wait_for_audit_action(
    workspace_id: str, action: str, timeout_secs: float = 5.0, *, interval: float = 0.02
) -> list[str]:
    """Poll the audit table until `action` lands for `workspace_id`.

    Each iteration opens a fresh SessionFactory session: a cached session can
    hold a stale read snapshot and never observe the consumer's commit.
    """
    from sqlalchemy import select

    from src.db.session import SessionFactory
    from src.models.audit import AuditLogEntry

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_secs
    actions: list[str] = []
    while True:
        async with SessionFactory() as session:
            actions = list(
                (
                    await session.execute(
                        select(AuditLogEntry.action).where(
                            AuditLogEntry.workspace_id == workspace_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        if action in actions or loop.time() >= deadline:
            break
        await asyncio.sleep(interval)
    assert action in actions, (
        f"audit bus did not commit {action} in {timeout_secs}s; saw {sorted(actions)}"
    )
    return actions
