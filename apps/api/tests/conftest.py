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

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from src import models as _models  # noqa: E402,F401  (register tables on Base.metadata)
from src.db.base import Base  # noqa: E402
from src.db.session import engine  # noqa: E402
from src.settings import settings  # noqa: E402

if TYPE_CHECKING:  # noqa: E402
    from src.models.jobs import JobRun


def _db_path() -> Path:
    """Filesystem path of the sqlite file the suite shares."""
    return Path(make_url(settings.resolved_database_url).database)


async def _discard_db_file() -> None:
    """Take the sqlite file away from every connection that is still open."""
    await engine.dispose()  # close this suite's pooled connections first
    _db_path().unlink(missing_ok=True)


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
