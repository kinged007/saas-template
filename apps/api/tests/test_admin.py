"""Superuser admin surface + workspace feature-flag gate (issue #20)."""

from tests.conftest import (
    auth_headers,
    create_workspace,
    login,
    register_user,
    ws_headers,
)


# conftest seeds SUPERADMIN_EMAIL=root@example.com, so this account
# bootstraps as superuser on registration.
async def _superuser(client):
    await register_user(client, "root@example.com", first_name="Root", last_name="Admin")
    return await login(client, "root@example.com")


async def test_non_superuser_gets_403(app_client):
    client = app_client
    user = await register_user(client, "plain@example.com")
    for path in ("/api/v1/admin/users", "/api/v1/admin/workspaces", "/api/v1/admin/audit"):
        resp = await client.get(path, headers=auth_headers(user))
        assert resp.status_code == 403, (path, resp.text)


async def test_user_lookup_detail_and_disable(app_client):
    client = app_client
    admin = await _superuser(client)
    target = await register_user(client, "target@example.com")
    ws = await create_workspace(client, target)

    # search finds the user (Refine flat filter style)
    resp = await client.get(
        "/api/v1/admin/users",
        params={"email_like": "target@"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    assert any(u["email"] == "target@example.com" for u in resp.json())

    # detail shows workspaces with roles
    me = await client.get("/api/v1/auth/me", headers=auth_headers(target))
    detail = await client.get(
        f"/api/v1/admin/users/{me.json()['id']}", headers=auth_headers(admin)
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["workspaces"][0]["name"] == ws["name"]
    assert detail.json()["workspaces"][0]["role"] == "owner"

    # disable → login refused
    patch = await client.patch(
        f"/api/v1/admin/users/{me.json()['id']}",
        json={"is_active": False},
        headers=auth_headers(admin),
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["is_active"] is False
    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": "target@example.com", "password": "Password123!"},
    )
    assert bad.status_code == 401, bad.text

    # re-enable → login works again
    await client.patch(
        f"/api/v1/admin/users/{me.json()['id']}",
        json={"is_active": True},
        headers=auth_headers(admin),
    )
    await login(client, "target@example.com")


async def test_cannot_disable_self(app_client):
    client = app_client
    admin = await _superuser(client)
    me = await client.get("/api/v1/auth/me", headers=auth_headers(admin))
    resp = await client.patch(
        f"/api/v1/admin/users/{me.json()['id']}",
        json={"is_active": False},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 409, resp.text


async def test_workspace_list_and_cross_workspace_audit(app_client):
    client = app_client
    admin = await _superuser(client)
    owner = await register_user(client, "wowner@example.com")
    ws = await create_workspace(client, owner, name="Widget Co")

    resp = await client.get("/api/v1/admin/workspaces", headers=auth_headers(admin))
    assert resp.status_code == 200, resp.text
    row = next(w for w in resp.json() if w["id"] == ws["id"])
    assert row["member_count"] == 1

    audit = await client.get("/api/v1/admin/audit", headers=auth_headers(admin))
    assert audit.status_code == 200, audit.text
    actions = {e["action"] for e in audit.json()}
    assert "workspace.created" in actions

    scoped = await client.get(
        "/api/v1/admin/audit",
        params={"workspace_id": ws["id"]},
        headers=auth_headers(admin),
    )
    assert scoped.status_code == 200, scoped.text
    assert {e["workspace_id"] for e in scoped.json()} == {ws["id"]}
    # enriched names for readable rows
    assert scoped.json()[0]["workspace_name"] == "Widget Co"

    # cross-field search: workspace name, user email, action, exact ids
    me = await client.get("/api/v1/auth/me", headers=auth_headers(owner))
    for term in ("Widget Co", "wowner@", "workspace.created", me.json()["id"], ws["id"]):
        found = await client.get(
            "/api/v1/admin/audit", params={"q": term}, headers=auth_headers(admin)
        )
        assert found.status_code == 200, (term, found.text)
        assert int(found.headers["x-total-count"]) >= 1, term
    empty = await client.get(
        "/api/v1/admin/audit", params={"q": "zzz-no-such-thing"}, headers=auth_headers(admin)
    )
    assert empty.json() == [] and empty.headers["x-total-count"] == "0"

    # workspace-scoped search: user email, action, actor id (same ?q= contract)
    wsh = ws_headers(owner, ws["id"])
    for term in ("wowner@", "workspace.created", me.json()["id"]):
        found = await client.get("/api/v1/audit", params={"q": term}, headers=wsh)
        assert found.status_code == 200, (term, found.text)
        assert int(found.headers["x-total-count"]) >= 1, term
    assert found.json()[0]["actor_email"] == "wowner@example.com"
    empty = await client.get(
        "/api/v1/audit", params={"q": "zzz-no-such-thing"}, headers=wsh
    )
    assert empty.json() == [] and empty.headers["x-total-count"] == "0"


async def test_invites_flag_gates_creation(app_client):
    client = app_client
    owner = await register_user(client, "flagowner@example.com")
    ws = await create_workspace(client, owner)
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    editor = next(r for r in roles.json() if r["name"] == "editor")

    from src.db.session import SessionFactory
    from src.models.workspace import Workspace

    async with SessionFactory() as session:
        w = await session.get(Workspace, ws["id"])
        w.flags = {"invites_enabled": False}
        await session.commit()

    resp = await client.post(
        "/api/v1/invitations",
        json={"email": "new@example.com", "role_id": editor["id"]},
        headers=ws_headers(owner, ws["id"]),
    )
    assert resp.status_code == 403, resp.text
