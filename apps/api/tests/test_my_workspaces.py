"""My workspaces list + leave (issue #173)."""

from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


async def test_list_shows_role_and_joined_at(app_client):
    client = app_client
    tokens = await register_user(client, "mine@example.com")
    ws = await create_workspace(client, tokens)
    resp = await client.get("/api/v1/workspaces", headers=auth_headers(tokens))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    mine = next(r for r in rows if r["id"] == ws["id"])
    assert mine["role"] == "owner", mine
    assert mine.get("joined_at"), mine


async def test_leave_removes_membership(app_client):
    client = app_client
    owner = await register_user(client, "leave-owner@example.com")
    ws = await create_workspace(client, owner)
    member = await register_user(client, "leaver@example.com")
    # invite member in via invitation flow
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    assert roles.status_code == 200, roles.text
    viewer = next(r for r in roles.json() if r["name"] == "viewer")
    inv = await client.post(
        "/api/v1/invitations",
        json={"email": "leaver@example.com", "role_id": viewer["id"]},
        headers=ws_headers(owner, ws["id"]),
    )
    assert inv.status_code == 201, inv.text
    acc = await client.post(
        "/api/v1/invitations/accept",
        params={"token": inv.json()["token"]},
        headers=auth_headers(member),
    )
    assert acc.status_code == 200, acc.text
    # leave
    resp = await client.delete(
        f"/api/v1/workspaces/{ws['id']}/membership", headers=auth_headers(member)
    )
    assert resp.status_code == 204, resp.text
    listed = await client.get("/api/v1/workspaces", headers=auth_headers(member))
    assert all(r["id"] != ws["id"] for r in listed.json())


async def test_owner_cannot_leave(app_client):
    client = app_client
    tokens = await register_user(client, "stay@example.com")
    ws = await create_workspace(client, tokens)
    resp = await client.delete(
        f"/api/v1/workspaces/{ws['id']}/membership", headers=auth_headers(tokens)
    )
    assert resp.status_code == 409, resp.text
