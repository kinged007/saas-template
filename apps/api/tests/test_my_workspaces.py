"""My workspaces list + leave (issue #173)."""

from sqlalchemy import select

from src.db.session import SessionFactory
from src.models.workspace import Workspace
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
    # /auth/me is the other workspace list the UI reads; same shape.
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.status_code == 200, me.text
    assert next(r for r in me.json()["workspaces"] if r["id"] == ws["id"]).get("joined_at")


async def test_session_branch_permissions_match_auth_me(app_client):
    """Issue #1436: GET /workspaces session rows carry the same nested
    permissions as /auth/me for the same principal."""
    client = app_client
    tokens = await register_user(client, "perms-parity@example.com")
    ws = await create_workspace(client, tokens)
    lst = await client.get("/api/v1/workspaces", headers=auth_headers(tokens))
    assert lst.status_code == 200, lst.text
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.status_code == 200, me.text
    row = next(r for r in lst.json() if r["id"] == ws["id"])
    nested = next(r for r in me.json()["workspaces"] if r["id"] == ws["id"])
    assert row["permissions"] == nested["permissions"]
    assert row["permissions"], f"expected non-empty owner perms, got {row}"
    assert (row["role"], row["permissions"]) == (nested["role"], nested["permissions"])


async def test_me_permissions_follow_role_registry_order(app_client):
    """Issue #1476: the top-level permissions union keeps the role's registry
    order (ordered dedup), not an alphabetical sort."""
    client = app_client
    owner = await register_user(client, "order-owner@example.com")
    ws = await create_workspace(client, owner)
    ordered = ["workspace:update", "member:read", "audit:read"]
    role = await client.post(
        "/api/v1/roles",
        json={"name": "scanner", "permissions": ordered},
        headers=ws_headers(owner, ws["id"]),
    )
    assert role.status_code == 201, role.text
    member = await register_user(client, "order-member@example.com")
    inv = await client.post(
        "/api/v1/invitations",
        json={"email": "order-member@example.com", "role_id": role.json()["id"]},
        headers=ws_headers(owner, ws["id"]),
    )
    assert inv.status_code == 201, inv.text
    acc = await client.post(
        "/api/v1/invitations/accept",
        params={"token": inv.json()["token"]},
        headers=auth_headers(member),
    )
    assert acc.status_code == 200, acc.text
    me = await client.get("/api/v1/auth/me", headers=auth_headers(member))
    assert me.status_code == 200, me.text
    assert me.json()["permissions"] == ordered


async def test_me_permissions_union_keeps_first_occurrence_across_memberships(app_client):
    """Issue #1568: across memberships the union resolves a permission held by
    two roles to its first occurrence in `list_workspaces` order — newest
    workspace first (`Workspace.created_at.desc()`), duplicates collapsing once.
    Pins that order; a re-sort would fail here."""
    client = app_client
    owner = await register_user(client, "first-occ-owner@example.com")
    ws_a = await create_workspace(client, owner, name="Workspace A")
    role_a = await client.post(
        "/api/v1/roles",
        json={
            "name": "a-scanner",
            "permissions": ["audit:read", "member:read", "workspace:update"],
        },
        headers=ws_headers(owner, ws_a["id"]),
    )
    assert role_a.status_code == 201, role_a.text
    ws_b = await create_workspace(client, owner, name="Workspace B")
    role_b = await client.post(
        "/api/v1/roles",
        json={"name": "b-scanner", "permissions": ["member:read", "audit:read"]},
        headers=ws_headers(owner, ws_b["id"]),
    )
    assert role_b.status_code == 201, role_b.text

    member = await register_user(client, "first-occ-member@example.com")
    for ws_id, role_id in (
        (ws_a["id"], role_a.json()["id"]),
        (ws_b["id"], role_b.json()["id"]),
    ):
        inv = await client.post(
            "/api/v1/invitations",
            json={"email": "first-occ-member@example.com", "role_id": role_id},
            headers=ws_headers(owner, ws_id),
        )
        assert inv.status_code == 201, inv.text
        acc = await client.post(
            "/api/v1/invitations/accept",
            params={"token": inv.json()["token"]},
            headers=auth_headers(member),
        )
        assert acc.status_code == 200, acc.text

    # created_at is a one-second server_default here, so two workspaces
    # created in the same test tie and the id breaks the tie
    # (`Workspace.created_at.desc(), Workspace.id.desc()`). Derive the
    # expectation from the documented order rather than hand-pinning a
    # timestamp: a re-sort or a scan-order tiebreak fails here.
    async with SessionFactory() as session:
        stamped = (
            await session.execute(
                select(Workspace.id, Workspace.created_at).where(
                    Workspace.id.in_([ws_a["id"], ws_b["id"]])
                )
            )
        ).all()
    order = [row[0] for row in sorted(stamped, key=lambda row: (row[1], row[0]), reverse=True)]
    grants = {
        ws_a["id"]: role_a.json()["permissions"],
        ws_b["id"]: role_b.json()["permissions"],
    }

    me = await client.get("/api/v1/auth/me", headers=auth_headers(member))
    assert me.status_code == 200, me.text
    assert [w["id"] for w in me.json()["workspaces"]] == order
    assert me.json()["permissions"] == list(
        dict.fromkeys(p for ws_id in order for p in grants[ws_id])
    )


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


async def test_api_key_cannot_leave(app_client):
    client = app_client
    owner = await register_user(client, "leave-key@example.com")
    ws = await create_workspace(client, owner)
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "k", "permissions": ["workspace:read"]},
        headers=ws_headers(owner, ws["id"]),
    )
    assert resp.status_code == 201, resp.text
    key = resp.json()["key"]
    resp = await client.delete(
        f"/api/v1/workspaces/{ws['id']}/membership",
        headers={"Authorization": f"Bearer {key}", "X-Workspace-ID": ws["id"]},
    )
    assert resp.status_code == 403, resp.text
