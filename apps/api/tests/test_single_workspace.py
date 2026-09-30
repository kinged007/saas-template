"""Single-workspace mode (SINGLE_WORKSPACE=1).

First login/register creates the workspace (owned by whoever arrives first,
normally the superadmin); every later login/register auto-joins the oldest
workspace with the role named by SINGLE_WORKSPACE_DEFAULT_ROLE (viewer by
default). Extra workspace creation and workspace deletion are rejected while
the flag is on.
"""

import pytest

from src.settings import settings
from tests.conftest import (
    auth_headers,
    break_single_workspace_join,
    create_workspace,
    login,
    register_user,
)


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


async def _first_workspace(app_client) -> tuple[dict, str]:
    tokens = await register_user(app_client, "first@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    ws = me.json()["workspaces"][0]
    return tokens, ws["id"]


async def test_configured_system_role_is_granted(app_client, single_workspace_on, monkeypatch):
    monkeypatch.setattr(settings, "single_workspace_default_role", "editor")
    _, ws_id = await _first_workspace(app_client)
    tokens = await register_user(app_client, "second@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert [(w["id"], w["role"]) for w in me.json()["workspaces"]] == [(ws_id, "editor")]


async def test_configured_custom_role_is_granted(app_client, single_workspace_on, monkeypatch):
    tokens, ws_id = await _first_workspace(app_client)
    headers = {**auth_headers(tokens), "X-Workspace-ID": ws_id}
    resp = await app_client.post(
        "/api/v1/roles", json={"name": "ops", "permissions": []}, headers=headers
    )
    assert resp.status_code in (200, 201), resp.text
    monkeypatch.setattr(settings, "single_workspace_default_role", "ops")

    joined = await register_user(app_client, "second@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(joined))
    assert [(w["id"], w["role"]) for w in me.json()["workspaces"]] == [(ws_id, "ops")]


async def test_role_created_with_padded_name_is_granted(
    app_client, single_workspace_on, monkeypatch
):
    # The role is created through a normal API call with padding; stripping
    # on write is what keeps it matchable as the configured default.
    tokens, ws_id = await _first_workspace(app_client)
    headers = {**auth_headers(tokens), "X-Workspace-ID": ws_id}
    resp = await app_client.post(
        "/api/v1/roles", json={"name": "  ops  ", "permissions": []}, headers=headers
    )
    assert resp.status_code in (200, 201), resp.text
    monkeypatch.setattr(settings, "single_workspace_default_role", "ops")

    joined = await register_user(app_client, "second@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(joined))
    assert [(w["id"], w["role"]) for w in me.json()["workspaces"]] == [(ws_id, "ops")]


async def test_unknown_role_name_falls_back_to_viewer(app_client, single_workspace_on, monkeypatch):
    await _first_workspace(app_client)
    for i, value in enumerate(["", "   ", "nope", "owner"]):
        monkeypatch.setattr(settings, "single_workspace_default_role", value)
        tokens = await register_user(app_client, f"newcomer{i}@example.com")
        me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
        assert me.json()["workspaces"][0]["role"] == "viewer", value


async def test_relogin_keeps_existing_member_role(app_client, single_workspace_on, monkeypatch):
    await _first_workspace(app_client)
    second = await register_user(app_client, "second@example.com")
    monkeypatch.setattr(settings, "single_workspace_default_role", "editor")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "second@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 200, resp.text
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(resp.json()))
    assert me.json()["workspaces"][0]["role"] == "viewer"
    assert second["access_token"]


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


async def test_login_survives_join_failure(app_client, single_workspace_on):
    # A failed join is log-only: the rollback it needs expires every loaded
    # instance, so the reads after it must not be lazy loads.
    await break_single_workspace_join(app_client)
    await register_user(app_client, "newcomer@example.com")

    tokens = await login(app_client, "newcomer@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.status_code == 200, me.text
    assert me.json()["workspaces"] == []
    assert me.json()["single_workspace"] is True


async def test_refresh_survives_join_failure(app_client, single_workspace_on):
    await break_single_workspace_join(app_client)
    tokens = await register_user(app_client, "newcomer@example.com")

    resp = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200, resp.text


async def test_register_survives_join_failure(app_client, single_workspace_on):
    await break_single_workspace_join(app_client)
    tokens = await register_user(app_client, "newcomer@example.com")

    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.status_code == 200, me.text
    assert me.json()["workspaces"] == []


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
