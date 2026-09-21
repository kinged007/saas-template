"""Admin surface: superuser-only user lookup, disable, workspace list, audit, flags."""

from __future__ import annotations

from tests.conftest import auth_headers, create_workspace, login, register_user


async def _superuser_client(app_client):
    client = app_client
    await register_user(client, "plain@example.com")
    tokens = await register_user(client, "root@example.com")  # SUPERADMIN_EMAIL
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.json()["is_superuser"] is True
    return client, tokens


async def test_admin_routes_require_superuser(app_client):
    client = app_client
    await register_user(client, "plain@example.com")
    plain = await login(client, "plain@example.com")
    for method, url in [
        ("get", "/api/v1/admin/users"),
        ("get", "/api/v1/admin/workspaces"),
        ("get", "/api/v1/admin/audit"),
    ]:
        resp = await client.request(method, url, headers=auth_headers(plain))
        assert resp.status_code == 403, (method, url, resp.text)


async def test_admin_user_lookup_and_disable(app_client):
    client, tokens = await _superuser_client(app_client)
    ws = await create_workspace(client, tokens, "Acme")

    resp = await client.get("/api/v1/admin/users?search=plain@", headers=auth_headers(tokens))
    assert resp.status_code == 200, resp.text
    users = resp.json()
    assert any(u["email"] == "plain@example.com" for u in users)
    assert resp.headers["X-Total-Count"]
    target = next(u for u in users if u["email"] == "plain@example.com")

    detail = await client.get(f"/api/v1/admin/users/{target['id']}", headers=auth_headers(tokens))
    assert detail.status_code == 200, detail.text
    assert detail.json()["email"] == "plain@example.com"
    assert isinstance(detail.json()["workspaces"], list)

    disable = await client.patch(
        f"/api/v1/admin/users/{target['id']}",
        json={"is_active": False},
        headers=auth_headers(tokens),
    )
    assert disable.status_code == 200, disable.text
    assert disable.json()["is_active"] is False

    # Disabled user can no longer log in.
    relogin = await client.post(
        "/api/v1/auth/login", json={"email": "plain@example.com", "password": "Password123!"}
    )
    assert relogin.status_code in (401, 403), relogin.text

    # Re-enable restores access.
    enable = await client.patch(
        f"/api/v1/admin/users/{target['id']}",
        json={"is_active": True},
        headers=auth_headers(tokens),
    )
    assert enable.status_code == 200, enable.text
    relogin2 = await client.post(
        "/api/v1/auth/login", json={"email": "plain@example.com", "password": "Password123!"}
    )
    assert relogin2.status_code == 200, relogin2.text
    assert ws["id"]


async def test_admin_cannot_disable_self(app_client):
    client, tokens = await _superuser_client(app_client)
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    resp = await client.patch(
        f"/api/v1/admin/users/{me.json()['id']}",
        json={"is_active": False},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 409, resp.text


async def test_admin_workspace_list_and_flags_gate_invites(app_client):
    client, tokens = await _superuser_client(app_client)
    ws = await create_workspace(client, tokens, "Acme")

    resp = await client.get("/api/v1/admin/workspaces", headers=auth_headers(tokens))
    assert resp.status_code == 200, resp.text
    assert any(w["id"] == ws["id"] for w in resp.json())

    flags = await client.patch(
        f"/api/v1/admin/workspaces/{ws['id']}/flags",
        json={"flags": {"invites_enabled": False}},
        headers=auth_headers(tokens),
    )
    assert flags.status_code == 200, flags.text
    assert flags.json()["flags"]["invites_enabled"] is False

    # Invitation creation now refuses.
    roles = await client.get(
        "/api/v1/roles", headers={**auth_headers(tokens), "X-Workspace-ID": ws["id"]}
    )
    role_id = next(r["id"] for r in roles.json() if r["name"] == "editor")
    invite = await client.post(
        "/api/v1/invitations",
        json={"email": "new@example.com", "role_id": role_id},
        headers={**auth_headers(tokens), "X-Workspace-ID": ws["id"]},
    )
    assert invite.status_code == 409, invite.text
    assert "disabled" in invite.text

    # Re-enable restores invites.
    await client.patch(
        f"/api/v1/admin/workspaces/{ws['id']}/flags",
        json={"flags": {"invites_enabled": True}},
        headers=auth_headers(tokens),
    )
    invite2 = await client.post(
        "/api/v1/invitations",
        json={"email": "new@example.com", "role_id": role_id},
        headers={**auth_headers(tokens), "X-Workspace-ID": ws["id"]},
    )
    assert invite2.status_code == 201, invite2.text


async def test_admin_user_update_rejects_non_bool(app_client):
    client, tokens = await _superuser_client(app_client)

    resp = await client.get("/api/v1/admin/users?search=plain@", headers=auth_headers(tokens))
    assert resp.status_code == 200, resp.text
    target = next(u for u in resp.json() if u["email"] == "plain@example.com")

    for bad in ("yes", 1, 0):
        resp = await client.patch(
            f"/api/v1/admin/users/{target['id']}",
            json={"is_active": bad},
            headers=auth_headers(tokens),
        )
        assert resp.status_code == 422, (bad, resp.text)

    detail = await client.get(f"/api/v1/admin/users/{target['id']}", headers=auth_headers(tokens))
    assert detail.status_code == 200, detail.text
    assert detail.json()["is_active"] is True


async def test_admin_flags_reject_non_bool(app_client):
    client, tokens = await _superuser_client(app_client)
    ws = await create_workspace(client, tokens, "Acme")

    for bad in ({"invites_enabled": "yes"}, {"invites_enabled": 1}, {"invites_enabled": 0}):
        resp = await client.patch(
            f"/api/v1/admin/workspaces/{ws['id']}/flags",
            json={"flags": bad},
            headers=auth_headers(tokens),
        )
        assert resp.status_code == 422, (bad, resp.text)

    # Stored flags unchanged after rejected writes.
    ws_list = await client.get("/api/v1/admin/workspaces", headers=auth_headers(tokens))
    row = next(w for w in ws_list.json() if w["id"] == ws["id"])
    assert "invites_enabled" not in row["flags"]


async def test_admin_audit_cross_workspace(app_client):
    import asyncio

    client, tokens = await _superuser_client(app_client)
    await create_workspace(client, tokens, "Acme")
    actions: list[str] = []
    for _ in range(150):
        resp = await client.get("/api/v1/admin/audit", headers=auth_headers(tokens))
        assert resp.status_code == 200, resp.text
        actions = [e["action"] for e in resp.json()]
        if "user.register" in actions and "workspace.created" in actions:
            break
        await asyncio.sleep(0.02)
    assert "user.register" in actions
    assert "workspace.created" in actions
    assert resp.headers["X-Total-Count"]
