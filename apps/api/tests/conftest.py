from __future__ import annotations

import asyncio  # noqa: E402
import os  # noqa: E402
from datetime import timedelta  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_saas_template.db"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["FERNET_KEYS"] = "test-fernet-key-value"
os.environ["EVENT_BUS_DRIVER"] = "inprocess"
os.environ["ENVIRONMENT"] = "test"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ["SUPERADMIN_EMAIL"] = "root@example.com"

import warnings  # noqa: E402

import pytest  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from src import models as _models  # noqa: E402,F401  (register tables on Base.metadata)
from src.db.base import Base  # noqa: E402
from src.db.session import engine  # noqa: E402
from src.settings import settings  # noqa: E402

if TYPE_CHECKING:  # noqa: E402
    from src.models.jobs import JobRun


async def _drop_all_with_retry(tries: int = 24, delay: float = 0.25) -> None:
    """Drop all tables, retrying transient sqlite locks.

    Background bus workers may still be draining their last transactions when a
    test ends; a fresh engine connection then blocks on the file lock. Dispose
    pooled connections first, then retry briefly.

    The drop runs on a dedicated engine with a *short* busy timeout: the
    background worker holding the lock always finishes within a few seconds, so
    waiting 30s (the app engine's timeout) per attempt only turns a transient
    contention into a multi-minute stall.

    The budget is ~6s: workspace provisioning (workspaces.created workflow)
    and scheduled-job workers add a little more post-test drain time than the
    notification workflows alone.
    """
    drop_engine = create_async_engine(settings.resolved_database_url, connect_args={"timeout": 2})
    try:
        for attempt in range(tries):
            try:
                await engine.dispose()  # force-close any leaked pooled connections
                await drop_engine.dispose()
                async with drop_engine.begin() as conn:
                    await conn.run_sync(Base.metadata.drop_all)
                return
            except Exception as exc:
                if attempt == tries - 1:
                    raise
                # ponytail: warn (not log — no logger configured in tests) so the next
                # flake shows it was lock contention and how many retries it took.
                msg = f"db drop attempt {attempt + 1}/{tries} failed, retrying: {exc}"
                warnings.warn(msg, stacklevel=2)
                await asyncio.sleep(delay)
    finally:
        await drop_engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_db():
    await _drop_all_with_retry()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await _drop_all_with_retry()


@pytest.fixture
async def app():
    from src.main import app as fastapi_app

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


async def run_job_via_scheduler(
    key: str,
    *,
    missed_by: timedelta = timedelta(hours=3),
    timeout_s: float = 10.0,
) -> tuple[JobRun, list[str]]:
    """Drive a global job through the real scheduler -> bus -> executor path.

    Backdates the provisioned definition's `next_run_at` so a tick claims it as
    a missed occurrence, then waits for the durable worker to finish the run.
    Returns the run plus its captured log messages.
    """
    from sqlalchemy import select

    from src.core.dates import now_utc
    from src.db.session import SessionFactory
    from src.jobs.scheduler import JobScheduler
    from src.main import app as fastapi_app
    from src.models.jobs import JobDefinition, JobLogEntry, JobRun

    async with SessionFactory() as session:
        definition = (
            await session.execute(
                select(JobDefinition).where(
                    JobDefinition.key == key,
                    JobDefinition.workspace_id.is_(None),
                )
            )
        ).scalar_one()
        assert definition.enabled is True, f"{key} is not enabled"
        definition.next_run_at = now_utc() - missed_by
        definition_id = definition.id
        await session.commit()

    await JobScheduler(bus=fastapi_app.state.container.bus).tick()

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
    raise AssertionError(f"job {key} did not finish within {timeout_s}s")
