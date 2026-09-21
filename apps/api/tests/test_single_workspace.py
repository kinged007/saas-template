"""Single-workspace mode (SINGLE_WORKSPACE=1).

First login/register creates the workspace (owned by whoever arrives first,
normally the superadmin); every later login/register auto-joins the oldest
workspace with the viewer role. Extra workspace creation and workspace
deletion are rejected while the flag is on.
"""

import pytest

from src.settings import settings
from tests.conftest import auth_headers, create_workspace, login, register_user


@pytest.fixture
def single_workspace_on(monkeypatch):
    monkeypatch.setattr(settings, "single_workspace", True)
    yield
    monkeypatch.setattr(settings, "single_workspace", False)


async def test_register_creates_single_workspace(app_client, single_workspace_on):
    tokens = await register_user(app_client, "first@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.status_code == 200
    body = me.json()
    assert len(body["workspaces"]) == 1
    assert body["workspaces"][0]["role"] == "owner"
    assert body["single_workspace"] is True


async def test_second_register_joins_same_workspace(app_client, single_workspace_on):
    first = await register_user(app_client, "first@example.com")
    me1 = await app_client.get("/api/v1/auth/me", headers=auth_headers(first))
    ws_id = me1.json()["workspaces"][0]["id"]

    second = await register_user(app_client, "second@example.com")
    me2 = await app_client.get("/api/v1/auth/me", headers=auth_headers(second))
    assert me2.status_code == 200
    assert len(me2.json()["workspaces"]) == 1
    assert me2.json()["workspaces"][0]["id"] == ws_id
    assert me2.json()["workspaces"][0]["role"] == "viewer"


async def test_login_joins_single_workspace(app_client, single_workspace_on):
    await register_user(app_client, "first@example.com")
    await register_user(app_client, "second@example.com")
    tokens = await login(app_client, "second@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert len(me.json()["workspaces"]) == 1


async def test_create_second_workspace_rejected(app_client, single_workspace_on):
    tokens = await register_user(app_client, "first@example.com")
    resp = await app_client.post(
        "/api/v1/workspaces", json={"name": "Second"}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 403


async def test_delete_workspace_rejected(app_client, single_workspace_on):
    tokens = await register_user(app_client, "first@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    ws_id = me.json()["workspaces"][0]["id"]
    resp = await app_client.delete(
        f"/api/v1/workspaces/{ws_id}",
        headers={**auth_headers(tokens), "X-Workspace-ID": ws_id},
    )
    assert resp.status_code == 403


async def test_flag_off_keeps_current_behavior(app_client):
    assert settings.single_workspace is False
    tokens = await register_user(app_client, "plain@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.json()["workspaces"] == []
    assert me.json()["single_workspace"] is False
    ws = await create_workspace(app_client, tokens)
    assert ws["id"]


async def test_refresh_joins_single_workspace(app_client, single_workspace_on, monkeypatch):
    # Registered before the flag was enabled: refresh heals the membership.
    monkeypatch.setattr(settings, "single_workspace", False)
    tokens = await register_user(app_client, "early@example.com")
    monkeypatch.setattr(settings, "single_workspace", True)
    first = await register_user(app_client, "first@example.com")
    me1 = await app_client.get("/api/v1/auth/me", headers=auth_headers(first))
    ws_id = me1.json()["workspaces"][0]["id"]

    resp = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200, resp.text
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(resp.json()))
    assert [w["id"] for w in me.json()["workspaces"]] == [ws_id]


async def test_join_survives_missing_viewer_role(app_client, single_workspace_on):
    from sqlalchemy import delete

    from src.db.session import SessionFactory
    from src.models.workspace import Role

    first = await register_user(app_client, "first@example.com")
    me1 = await app_client.get("/api/v1/auth/me", headers=auth_headers(first))
    ws_id = me1.json()["workspaces"][0]["id"]
    async with SessionFactory() as session:
        await session.execute(delete(Role).where(Role.workspace_id == ws_id, Role.name == "viewer"))
        await session.commit()
    # No 500: login succeeds and the newcomer still joins (fallback role).
    tokens = await register_user(app_client, "second@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert [w["id"] for w in me.json()["workspaces"]] == [ws_id]


async def test_join_failure_does_not_break_login(app_client, single_workspace_on, monkeypatch):
    import src.api.routes.auth as auth_routes

    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(auth_routes.WorkspaceService, "join_single_workspace", boom)
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@example.com", "password": "Password123!"},
    )
    # Unknown user still 401; the point is no 500 from the join path —
    # covered below with a real user.
    assert resp.status_code == 401
    monkeypatch.setattr(settings, "single_workspace", False)
    await register_user(app_client, "real@example.com")
    monkeypatch.setattr(settings, "single_workspace", True)
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "real@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 200, resp.text


async def test_delete_nonexistent_returns_404_in_single_mode(app_client, single_workspace_on):
    tokens = await register_user(app_client, "first@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    ws_id = me.json()["workspaces"][0]["id"]
    resp = await app_client.delete(
        "/api/v1/workspaces/00000000-0000-0000-0000-000000000000",
        headers={**auth_headers(tokens), "X-Workspace-ID": ws_id},
    )
    assert resp.status_code == 404


async def test_oldest_workspace_wins(app_client, single_workspace_on, monkeypatch):
    # Pre-existing workspaces: auto-join picks the oldest, extras stay hidden.
    monkeypatch.setattr(settings, "single_workspace", False)
    tokens = await register_user(app_client, "owner@example.com")
    ws1 = await create_workspace(app_client, tokens, "First")
    ws2 = await create_workspace(app_client, tokens, "Second")
    assert ws1["id"] != ws2["id"]
    monkeypatch.setattr(settings, "single_workspace", True)

    newcomer = await register_user(app_client, "newcomer@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(newcomer))
    assert [w["id"] for w in me.json()["workspaces"]] == [ws1["id"]]
