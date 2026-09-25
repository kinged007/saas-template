import asyncio  # noqa: E402
import os  # noqa: E402

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
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


async def create_workspace(client: AsyncClient, tokens: dict, name: str = "Test Workspace") -> dict:
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
