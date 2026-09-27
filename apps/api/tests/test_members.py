from tests.conftest import (
    auth_headers,
    create_workspace,
    register_user,
    ws_headers,
)


async def _add_member(client, owner_tokens, ws, email: str, role_name: str) -> dict:
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner_tokens, ws["id"]))
    role = next(r for r in roles.json() if r["name"] == role_name)
    resp = await client.post(
        "/api/v1/invitations",
        json={"email": email, "role_id": role["id"]},
        headers=ws_headers(owner_tokens, ws["id"]),
    )
    invite = resp.json()
    user = await register_user(client, email)
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(user),
    )
    members = await client.get("/api/v1/members", headers=ws_headers(owner_tokens, ws["id"]))
    return user, next(m for m in members.json() if m["email"] == email)


async def _members(client, headers) -> list[dict]:
    resp = await client.get("/api/v1/members", headers=headers)
    assert resp.status_code == 200
    return resp.json()


async def _role_id(client, headers, name: str) -> str:
    roles = await client.get("/api/v1/roles", headers=headers)
    return next(r for r in roles.json() if r["name"] == name)["id"]


async def test_owner_cannot_change_own_role(app_client):
    client = app_client
    owner = await register_user(client, "tom@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    owner_member = next(
        m for m in await _members(client, owner_headers) if m["email"] == "tom@example.com"
    )
    viewer_id = await _role_id(client, owner_headers, "viewer")

    resp = await client.patch(
        f"/api/v1/members/{owner_member['membership_id']}",
        json={"role_id": viewer_id},
        headers=owner_headers,
    )
    assert resp.status_code == 409
    assert "owner" in resp.json()["detail"]


async def test_owner_role_cannot_be_assigned_to_anyone(app_client):
    client = app_client
    owner = await register_user(client, "uma@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    _, member = await _add_member(client, owner, ws, "viv@example.com", "viewer")
    owner_id = await _role_id(client, owner_headers, "owner")

    resp = await client.patch(
        f"/api/v1/members/{member['membership_id']}",
        json={"role_id": owner_id},
        headers=owner_headers,
    )
    assert resp.status_code == 409
    assert "owner" in resp.json()["detail"]


async def test_admin_cannot_set_owner_role(app_client):
    client = app_client
    owner = await register_user(client, "will@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    admin, _ = await _add_member(client, owner, ws, "xena@example.com", "admin")
    _, member = await _add_member(client, owner, ws, "yves@example.com", "viewer")
    owner_id = await _role_id(client, owner_headers, "owner")

    resp = await client.patch(
        f"/api/v1/members/{member['membership_id']}",
        json={"role_id": owner_id},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 409
    assert "owner" in resp.json()["detail"]


async def test_admin_can_change_other_member_role(app_client):
    client = app_client
    owner = await register_user(client, "zoe@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    admin, _ = await _add_member(client, owner, ws, "abby@example.com", "admin")
    _, member = await _add_member(client, owner, ws, "bob@example.com", "viewer")
    editor_id = await _role_id(client, owner_headers, "editor")

    resp = await client.patch(
        f"/api/v1/members/{member['membership_id']}",
        json={"role_id": editor_id},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 200
    members = await _members(client, owner_headers)
    assert next(m for m in members if m["email"] == "bob@example.com")["role"] == "editor"


async def test_non_manager_cannot_change_role(app_client):
    client = app_client
    owner = await register_user(client, "carl@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    viewer, _ = await _add_member(client, owner, ws, "dana@example.com", "viewer")
    _, member = await _add_member(client, owner, ws, "eve@example.com", "viewer")
    editor_id = await _role_id(client, owner_headers, "editor")

    resp = await client.patch(
        f"/api/v1/members/{member['membership_id']}",
        json={"role_id": editor_id},
        headers=ws_headers(viewer, ws["id"]),
    )
    assert resp.status_code == 403


async def test_list_members_pagination(app_client):
    client = app_client
    owner = await register_user(client, "page_owner@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    await _add_member(client, owner, ws, "page_a@example.com", "viewer")
    await _add_member(client, owner, ws, "page_b@example.com", "viewer")

    resp = await client.get("/api/v1/members?limit=2&offset=0", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    assert len(resp.json()) == 2

    resp = await client.get("/api/v1/members?limit=2&offset=2", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    assert len(resp.json()) == 1

    resp = await client.get("/api/v1/members?_start=2&_end=4", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    assert len(resp.json()) == 1
