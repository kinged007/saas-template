import os  # noqa: E402

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
from src.db import session as session_module  # noqa: E402
from src.db.base import Base  # noqa: E402
from src.db.session import SessionFactory  # noqa: E402


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
