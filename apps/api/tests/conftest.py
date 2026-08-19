import asyncio  # noqa: E402
import os  # noqa: E402

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_saas_template.db"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["FERNET_KEYS"] = "test-fernet-key-value"
os.environ["EVENT_BUS_DRIVER"] = "inprocess"
os.environ["ENVIRONMENT"] = "test"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"

import pytest  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from src import models as _models  # noqa: E402,F401  (register tables on Base.metadata)
from src.db.base import Base  # noqa: E402
from src.db.session import engine  # noqa: E402


async def _drop_all_with_retry(tries: int = 10, delay: float = 0.5) -> None:
    """Drop all tables, retrying transient sqlite locks.

    Background bus workers may still be draining their last transactions when a
    test ends; a fresh engine connection then blocks on the file lock. Dispose
    pooled connections first, then retry briefly.
    """
    for attempt in range(tries):
        try:
            await engine.dispose()  # force-close any leaked pooled connections
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            return
        except Exception:
            if attempt == tries - 1:
                raise
            await asyncio.sleep(delay)


@pytest.fixture(autouse=True)
async def _clean_db():
    await _drop_all_with_retry()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await _drop_all_with_retry()


@pytest.fixture
async def app_client():
    from src.main import app

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def register_user(client: AsyncClient, email: str = "user@example.com") -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "display_name": "Test User"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


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
