"""Single-workspace mode (SINGLE_WORKSPACE=1).

First login/register creates the workspace (owned by whoever arrives first,
normally the superadmin); every later login/register auto-joins the oldest
workspace with the role named by SINGLE_WORKSPACE_DEFAULT_ROLE (viewer by
default). Extra workspace creation and workspace deletion are rejected while
the flag is on.
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


async def test_unknown_role_name_falls_back_to_viewer(app_client, single_workspace_on, monkeypatch):
    await _first_workspace(app_client)
    for i, value in enumerate(["", "   ", "nope", "owner"]):
        monkeypatch.setattr(settings, "single_workspace_default_role", value)
        tokens = await register_user(app_client, f"newcomer{i}@example.com")
        me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
        assert me.json()["workspaces"][0]["role"] == "viewer", value


async def test_relogin_keeps_existing_member_role(app_client, single_workspace_on, monkeypatch):
    await _first_workspace(app_client)
    await register_user(app_client, "second@example.com")
    monkeypatch.setattr(settings, "single_workspace_default_role", "editor")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "second@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 200, resp.text
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(resp.json()))
    assert me.json()["workspaces"][0]["role"] == "viewer"


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


async def _retire_system_roles(app_client, created_at: list) -> str:
    """Leave the workspace owner plus two custom roles, newest inserted first.

    Dropping admin/editor/viewer is what forces the last-resort branch.
    Returns the workspace id; `created_at` is per custom role, in insert order.
    """
    from sqlalchemy import delete

    from src.db.session import SessionFactory
    from src.models.workspace import Role

    _, ws_id = await _first_workspace(app_client)
    async with SessionFactory() as session:
        await session.execute(
            delete(Role).where(
                Role.workspace_id == ws_id, Role.name.in_(["admin", "editor", "viewer"])
            )
        )
        session.add_all(
            Role(workspace_id=ws_id, name=name, permissions=[], created_at=stamp)
            for name, stamp in zip(["zulu", "alpha"], created_at, strict=True)
        )
        await session.commit()
    return ws_id


async def test_last_resort_role_is_the_oldest_remaining_role(
    app_client, single_workspace_on, caplog
):
    import logging
    from datetime import timedelta

    from src.core.dates import now_utc

    base = now_utc()
    ws_id = await _retire_system_roles(app_client, [base + timedelta(days=1), base])
    with caplog.at_level(logging.WARNING, logger="src.services.workspaces"):
        tokens = await register_user(app_client, "second@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert [(w["id"], w["role"]) for w in me.json()["workspaces"]] == [(ws_id, "alpha")]
    # The last resort is the branch an operator most needs to know about.
    assert "granting oldest remaining role 'alpha'" in caplog.text


async def test_last_resort_role_breaks_timestamp_ties_by_name(app_client, single_workspace_on):
    from src.core.dates import now_utc

    # Roles created in one transaction share a created_at; the pick must still be stable.
    base = now_utc()
    ws_id = await _retire_system_roles(app_client, [base, base])
    tokens = await register_user(app_client, "second@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert [(w["id"], w["role"]) for w in me.json()["workspaces"]] == [(ws_id, "alpha")]


async def test_unresolvable_default_role_is_logged(
    app_client, single_workspace_on, monkeypatch, caplog
):
    import logging

    from sqlalchemy import delete

    from src.db.session import SessionFactory
    from src.models.workspace import Role

    _, ws_id = await _first_workspace(app_client)
    # Only viewer is gone, so the chain lands on editor: the log must name the
    # role actually granted, not the constant it no longer reaches.
    async with SessionFactory() as session:
        await session.execute(delete(Role).where(Role.workspace_id == ws_id, Role.name == "viewer"))
        await session.commit()
    monkeypatch.setattr(settings, "single_workspace_default_role", "edtior")
    with caplog.at_level(logging.WARNING, logger="src.services.workspaces"):
        tokens = await register_user(app_client, "second@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.json()["workspaces"][0]["role"] == "editor"
    assert "SINGLE_WORKSPACE_DEFAULT_ROLE='edtior'" in caplog.text
    assert "granted 'editor'" in caplog.text


async def test_resolvable_default_role_logs_nothing(
    app_client, single_workspace_on, monkeypatch, caplog
):
    import logging

    await _first_workspace(app_client)
    for value in ("viewer", "owner"):
        monkeypatch.setattr(settings, "single_workspace_default_role", value)
        with caplog.at_level(logging.WARNING, logger="src.services.workspaces"):
            tokens = await register_user(app_client, f"{value}-cfg@example.com")
        me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
        # "owner" is a documented input that resolves viewer: not a misconfiguration.
        assert me.json()["workspaces"][0]["role"] == "viewer"
        assert "SINGLE_WORKSPACE_DEFAULT_ROLE" not in caplog.text
        assert "granting oldest remaining role" not in caplog.text


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
