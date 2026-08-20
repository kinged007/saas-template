"""Security tests for API key authentication and authorization.

Covers, end to end over the HTTP API:
  * creation caps — a key can never be minted with a permission its creator
    does not hold (every escalation vector, wildcard, non-member callers)
  * read access — a key can read exactly the resources its permission list
    grants, and nothing else
  * edit access — PATCH/POST mutations require the matching permission
  * delete access — DELETE mutations require the matching permission
  * workspace scoping — a key minted in one workspace can never touch another
  * authentication hygiene — garbage/revoked keys, zero-permission keys,
    and proof that key permissions never inherit the creator's role
"""

from src.core.permissions import ALL_PERMISSIONS, permissions_for_role
from src.db.session import SessionFactory
from src.services.notifications import NotificationService
from tests.conftest import (
    auth_headers,
    create_workspace,
    register_user,
    ws_headers,
)

# ---------------------------------------------------------------- helpers


async def _add_member(client, owner_headers, ws_id, email, role_name):
    """Register + invite + accept: returns the new member's tokens."""
    member = await register_user(client, email)
    roles = await client.get("/api/v1/roles", headers=owner_headers)
    role = next(r for r in roles.json() if r["name"] == role_name)
    invite = await client.post(
        "/api/v1/invitations",
        json={"email": email, "role_id": role["id"]},
        headers=owner_headers,
    )
    assert invite.status_code == 201, invite.text
    resp = await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite.json()["token"]},
        headers=auth_headers(member),
    )
    assert resp.status_code == 200, resp.text
    return member


async def _create_key(client, headers, name, permissions):
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": name, "permissions": permissions},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _key_headers(raw: str, ws_id: str) -> dict:
    return {"Authorization": f"Bearer {raw}", "X-Workspace-ID": ws_id}


async def _user_id(client, tokens) -> str:
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.status_code == 200, me.text
    return me.json()["id"]


async def _membership_id(client, headers, ws_id, email) -> str:
    rows = await client.get("/api/v1/members", headers=headers)
    assert rows.status_code == 200, rows.text
    return next(m["membership_id"] for m in rows.json() if m["email"] == email)


async def _role_id(client, headers, ws_id, role_name) -> str:
    roles = await client.get("/api/v1/roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return next(r["id"] for r in roles.json() if r["name"] == role_name)


async def _insert_notification(ws_id: str, user_id: str, title: str = "Test alert") -> str:
    async with SessionFactory() as session:
        n = await NotificationService(session).create(
            user_id=user_id, workspace_id=ws_id, type="test", title=title
        )
        return n.id


# --------------------------------------------------------- creation caps


async def test_every_permission_an_editor_lacks_is_rejected(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    editor = await _add_member(
        client, ws_headers(owner, ws["id"]), ws["id"], "eve@example.com", "editor"
    )
    editor_headers = ws_headers(editor, ws["id"])

    editor_perms = set(permissions_for_role("editor"))
    denied = [p for p in ALL_PERMISSIONS if p not in editor_perms]
    assert denied, "editor should lack at least one permission for this test to mean anything"

    # every single permission the editor lacks → rejected
    for perm in denied:
        resp = await client.post(
            "/api/v1/api-keys",
            json={"name": f"denied-{perm}", "permissions": [perm]},
            headers=editor_headers,
        )
        assert resp.status_code == 403, (
            f"{perm} should be denied, got {resp.status_code}: {resp.text}"
        )
        assert perm in resp.json()["detail"]

    # every permission the editor holds → granted
    for perm in sorted(editor_perms):
        key = await _create_key(client, editor_headers, f"ok-{perm}", [perm])
        assert key["permissions"] == [perm]

    # a partial superset (mix of held + unheld) is still rejected wholesale
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "mixed", "permissions": ["member:read", "workspace:delete"]},
        headers=editor_headers,
    )
    assert resp.status_code == 403
    assert "workspace:delete" in resp.json()["detail"]


async def test_wildcard_escalation_rejected(app_client):
    client = app_client
    owner = await register_user(client, "bob@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    editor = await _add_member(client, owner_headers, ws["id"], "frank@example.com", "editor")
    viewer = await _add_member(client, owner_headers, ws["id"], "gina@example.com", "viewer")

    for headers in (ws_headers(editor, ws["id"]), ws_headers(viewer, ws["id"])):
        for perms in (["*"], ["*", "member:read"], ["member:read", "*"]):
            resp = await client.post(
                "/api/v1/api-keys", json={"name": "wild", "permissions": perms}, headers=headers
            )
            assert resp.status_code == 403, f"{perms} should be rejected: {resp.text}"


async def test_non_member_cannot_create_api_key(app_client):
    client = app_client
    owner = await register_user(client, "hank@example.com")
    ws = await create_workspace(client, owner)
    outsider = await register_user(client, "iris@example.com")

    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "sneaky", "permissions": []},
        headers=ws_headers(outsider, ws["id"]),
    )
    assert resp.status_code == 403
    assert "not a member" in resp.json()["detail"]


async def test_stored_permissions_match_granted_exactly(app_client):
    client = app_client
    owner = await register_user(client, "jane@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    requested = ["role:read", "member:read"]
    key = await _create_key(client, headers, "exact", requested)

    async with SessionFactory() as session:
        from src.models.api_key import ApiKey

        row = await session.get(ApiKey, key["id"])
        assert sorted(row.permissions) == sorted(requested)


# ------------------------------------------------------------- read access


async def test_key_reads_within_its_permission_scope(app_client):
    client = app_client
    owner = await register_user(client, "kim@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    owner_id = await _user_id(client, owner)

    # notifications need at least one row to be visible
    await _insert_notification(ws["id"], owner_id)

    cases = [
        ("member:read", "GET", "/api/v1/members", None),
        ("role:read", "GET", "/api/v1/roles", None),
        ("workspace:read", "GET", f"/api/v1/workspaces/{ws['id']}", None),
        ("apikey:read", "GET", "/api/v1/api-keys", None),
        ("notification:read", "GET", "/api/v1/notifications", None),
    ]
    for perm, method, path, _ in cases:
        key = await _create_key(client, headers, f"read-{perm}", [perm])
        resp = await client.request(method, path, headers=_key_headers(key["key"], ws["id"]))
        assert resp.status_code == 200, f"{perm} should read {path}: {resp.status_code} {resp.text}"

    # the notification:read key actually sees the notification
    nkey = await _create_key(client, headers, "n-read", ["notification:read"])
    resp = await client.get("/api/v1/notifications", headers=_key_headers(nkey["key"], ws["id"]))
    assert resp.status_code == 200
    assert any(n["workspace_id"] == ws["id"] for n in resp.json())

    # a workspace:read key can list workspaces, scoped to exactly its workspace
    wkey = await _create_key(client, headers, "w-read", ["workspace:read"])
    resp = await client.get("/api/v1/workspaces", headers=_key_headers(wkey["key"], ws["id"]))
    assert resp.status_code == 200
    assert [w["id"] for w in resp.json()] == [ws["id"]]


async def test_key_cannot_read_outside_its_permission_scope(app_client):
    client = app_client
    owner = await register_user(client, "leo@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    owner_id = await _user_id(client, owner)
    await _insert_notification(ws["id"], owner_id)

    # each single-permission key must be denied on every resource it lacks
    key = await _create_key(client, headers, "read-only", ["member:read"])
    kh = _key_headers(key["key"], ws["id"])
    for path in (
        "/api/v1/roles",
        f"/api/v1/workspaces/{ws['id']}",
        "/api/v1/api-keys",
        "/api/v1/notifications",
        "/api/v1/invitations/mine",
    ):
        resp = await client.get(path, headers=kh)
        assert resp.status_code == 403, f"member:read key must not read {path}: {resp.status_code}"

    key = await _create_key(client, headers, "role-read", ["role:read"])
    assert (
        await client.get("/api/v1/members", headers=_key_headers(key["key"], ws["id"]))
    ).status_code == 403

    key = await _create_key(client, headers, "ws-read", ["workspace:read"])
    assert (
        await client.get("/api/v1/members", headers=_key_headers(key["key"], ws["id"]))
    ).status_code == 403

    key = await _create_key(client, headers, "apikey-read", ["apikey:read"])
    assert (
        await client.get("/api/v1/members", headers=_key_headers(key["key"], ws["id"]))
    ).status_code == 403

    key = await _create_key(client, headers, "notif-read", ["notification:read"])
    assert (
        await client.get("/api/v1/members", headers=_key_headers(key["key"], ws["id"]))
    ).status_code == 403


# ------------------------------------------------------------- edit access


async def test_edit_operations_require_matching_key_permission(app_client):
    client = app_client
    owner = await register_user(client, "mia@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    owner_id = await _user_id(client, owner)

    eve = await _add_member(client, headers, ws["id"], "eve@example.com", "editor")
    eve_membership = await _membership_id(client, headers, ws["id"], "eve@example.com")
    viewer_role = await _role_id(client, headers, ws["id"], "viewer")

    # minted while eve is still an editor: key may only carry her permissions
    eve_read = await _create_key(client, ws_headers(eve, ws["id"]), "eve-read", ["member:read"])

    read_key = await _create_key(client, headers, "read-only", ["member:read"])
    read_kh = _key_headers(read_key["key"], ws["id"])

    # member:manage — role change
    manage_key = await _create_key(client, headers, "member-manage", ["member:manage"])
    manage_kh = _key_headers(manage_key["key"], ws["id"])
    resp = await client.patch(
        f"/api/v1/members/{eve_membership}",
        json={"role_id": viewer_role},
        headers=manage_kh,
    )
    assert resp.status_code == 200, resp.text
    # sanity: owner still sees the member list
    assert (await client.get("/api/v1/members", headers=headers)).json()[0]
    resp = await client.patch(
        f"/api/v1/members/{eve_membership}",
        json={"role_id": viewer_role},
        headers=read_kh,
    )
    assert resp.status_code == 403

    # workspace:update — rename
    ws_key = await _create_key(client, headers, "ws-update", ["workspace:update"])
    ws_kh = _key_headers(ws_key["key"], ws["id"])
    resp = await client.patch(
        f"/api/v1/workspaces/{ws['id']}", json={"name": "Renamed"}, headers=ws_kh
    )
    assert resp.status_code == 200, resp.text
    resp = await client.patch(
        f"/api/v1/workspaces/{ws['id']}", json={"name": "Nope"}, headers=read_kh
    )
    assert resp.status_code == 403

    # role:manage — create a custom role
    role_key = await _create_key(client, headers, "role-manage", ["role:manage"])
    role_kh = _key_headers(role_key["key"], ws["id"])
    resp = await client.post(
        "/api/v1/roles",
        json={"name": "auditor", "description": "x", "permissions": ["member:read"]},
        headers=role_kh,
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/api/v1/roles",
        json={"name": "auditor2", "description": "x", "permissions": []},
        headers=read_kh,
    )
    assert resp.status_code == 403

    # notification:acknowledge — mark read
    nid = await _insert_notification(ws["id"], owner_id)
    nkey = await _create_key(client, headers, "notif-ack", ["notification:acknowledge"])
    nkh = _key_headers(nkey["key"], ws["id"])
    resp = await client.patch(
        f"/api/v1/notifications/{nid}", json={"acknowledged": True}, headers=nkh
    )
    assert resp.status_code == 200, resp.text
    resp = await client.patch(
        f"/api/v1/notifications/{nid}", json={"acknowledged": True}, headers=read_kh
    )
    assert resp.status_code == 403

    # key minted by the editor (who has no member:manage) cannot change roles
    resp = await client.patch(
        f"/api/v1/members/{eve_membership}",
        json={"role_id": viewer_role},
        headers=_key_headers(eve_read["key"], ws["id"]),
    )
    assert resp.status_code == 403


# ------------------------------------------------------------ delete access


async def test_delete_operations_require_matching_key_permission(app_client):
    client = app_client
    owner = await register_user(client, "nina@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    owner_id = await _user_id(client, owner)

    await _add_member(client, headers, ws["id"], "eve@example.com", "editor")
    eve_membership = await _membership_id(client, headers, ws["id"], "eve@example.com")

    read_key = await _create_key(client, headers, "read-only", ["member:read"])
    read_kh = _key_headers(read_key["key"], ws["id"])

    # member:manage — remove a member
    manage_key = await _create_key(client, headers, "member-manage", ["member:manage"])
    manage_kh = _key_headers(manage_key["key"], ws["id"])
    resp = await client.delete(f"/api/v1/members/{eve_membership}", headers=manage_kh)
    assert resp.status_code == 204
    assert (
        await client.delete(f"/api/v1/members/{eve_membership}", headers=read_kh)
    ).status_code == 403

    # apikey:manage — revoke another key
    victim = await _create_key(client, headers, "victim", ["member:read"])
    revoke_key = await _create_key(client, headers, "revoker", ["apikey:manage"])
    revoke_kh = _key_headers(revoke_key["key"], ws["id"])
    resp = await client.delete(f"/api/v1/api-keys/{victim['id']}", headers=revoke_kh)
    assert resp.status_code == 204
    keys = await client.get("/api/v1/api-keys", headers=headers)
    assert next(k for k in keys.json() if k["id"] == victim["id"])["revoked_at"] is not None
    resp = await client.delete(f"/api/v1/api-keys/{victim['id']}", headers=read_kh)
    assert resp.status_code == 403

    # notification delete — gated like acknowledge
    nid = await _insert_notification(ws["id"], owner_id)
    nkey = await _create_key(client, headers, "notif-ack", ["notification:acknowledge"])
    nkh = _key_headers(nkey["key"], ws["id"])
    resp = await client.delete(f"/api/v1/notifications/{nid}", headers=nkh)
    assert resp.status_code == 204
    nid2 = await _insert_notification(ws["id"], owner_id)
    resp = await client.delete(f"/api/v1/notifications/{nid2}", headers=read_kh)
    assert resp.status_code == 403

    # workspace:delete — owner-only capability, delete via the key
    del_ws = await create_workspace(client, owner, name="Doomed")
    del_key = await _create_key(
        client, ws_headers(owner, del_ws["id"]), "ws-delete", ["workspace:delete"]
    )
    resp = await client.delete(
        f"/api/v1/workspaces/{del_ws['id']}", headers=_key_headers(del_key["key"], del_ws["id"])
    )
    assert resp.status_code == 204
    resp = await client.get(
        f"/api/v1/workspaces/{del_ws['id']}",
        headers=ws_headers(owner, del_ws["id"]),
    )
    assert resp.status_code == 404

    resp = await client.delete(
        f"/api/v1/workspaces/{del_ws['id']}", headers=_key_headers(read_key["key"], del_ws["id"])
    )
    assert resp.status_code == 403


# ------------------------------------------------------- workspace scoping


async def test_key_cannot_cross_workspace_boundaries(app_client):
    client = app_client
    owner = await register_user(client, "olga@example.com")
    ws_a = await create_workspace(client, owner, name="Alpha")
    ws_b = await create_workspace(client, owner, name="Beta")
    owner_id = await _user_id(client, owner)
    await _insert_notification(ws_a["id"], owner_id)
    await _insert_notification(ws_b["id"], owner_id)

    key = await _create_key(client, ws_headers(owner, ws_a["id"]), "a-read", ["member:read"])
    # header says Beta, key lives in Alpha → 403 before any query runs
    resp = await client.get("/api/v1/members", headers=_key_headers(key["key"], ws_b["id"]))
    assert resp.status_code == 403

    wkey = await _create_key(client, ws_headers(owner, ws_a["id"]), "a-ws-read", ["workspace:read"])
    resp = await client.get(
        f"/api/v1/workspaces/{ws_b['id']}", headers=_key_headers(wkey["key"], ws_b["id"])
    )
    assert resp.status_code == 403
    resp = await client.get(
        f"/api/v1/workspaces/{ws_a['id']}", headers=_key_headers(wkey["key"], ws_a["id"])
    )
    assert resp.status_code == 200
    resp = await client.get("/api/v1/workspaces", headers=_key_headers(wkey["key"], ws_a["id"]))
    assert resp.status_code == 200
    assert [w["id"] for w in resp.json()] == [ws_a["id"]]

    nkey = await _create_key(
        client, ws_headers(owner, ws_a["id"]), "a-notif", ["notification:read"]
    )
    resp = await client.get("/api/v1/notifications", headers=_key_headers(nkey["key"], ws_b["id"]))
    assert resp.status_code == 403
    resp = await client.get("/api/v1/notifications", headers=_key_headers(nkey["key"], ws_a["id"]))
    assert resp.status_code == 200
    assert all(n["workspace_id"] == ws_a["id"] for n in resp.json())

    akey = await _create_key(client, ws_headers(owner, ws_a["id"]), "a-apikey", ["apikey:read"])
    resp = await client.get("/api/v1/api-keys", headers=_key_headers(akey["key"], ws_b["id"]))
    assert resp.status_code == 403


# ------------------------------------------------- authentication hygiene


async def test_zero_permission_key_authenticates_but_can_do_nothing(app_client):
    client = app_client
    owner = await register_user(client, "pia@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    key = await _create_key(client, headers, "empty", [])
    kh = _key_headers(key["key"], ws["id"])

    # 403 (authenticated, denied) rather than 401 (unauthenticated) proves the
    # key was accepted as a credential but granted nothing.
    for method, path in (
        ("GET", "/api/v1/members"),
        ("GET", "/api/v1/roles"),
        ("GET", "/api/v1/api-keys"),
        ("GET", "/api/v1/notifications"),
        ("GET", f"/api/v1/workspaces/{ws['id']}"),
        ("GET", "/api/v1/workspaces"),
        ("GET", "/api/v1/invitations/mine"),
        ("GET", "/api/v1/api-keys/effective-permissions"),
    ):
        resp = await client.request(method, path, headers=kh)
        assert resp.status_code == 403, f"{method} {path} should be 403, got {resp.status_code}"

    # POST /workspaces needs a body to reach the authorization gate
    resp = await client.post("/api/v1/workspaces", json={"name": "Sneaky"}, headers=kh)
    assert resp.status_code == 403, f"POST /api/v1/workspaces should be 403, got {resp.status_code}"


async def test_session_and_key_permissions_are_independent(app_client):
    client = app_client
    owner = await register_user(client, "quinn@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    await _add_member(client, headers, ws["id"], "eve@example.com", "editor")
    eve_membership = await _membership_id(client, headers, ws["id"], "eve@example.com")
    viewer_role = await _role_id(client, headers, ws["id"], "viewer")

    # the owner's session can change roles (role has member:manage)...
    resp = await client.patch(
        f"/api/v1/members/{eve_membership}",
        json={"role_id": viewer_role},
        headers=headers,
    )
    assert resp.status_code == 200

    # ...but a key minted by the same owner without member:manage cannot
    key = await _create_key(client, headers, "read-only", ["member:read"])
    resp = await client.patch(
        f"/api/v1/members/{eve_membership}",
        json={"role_id": viewer_role},
        headers=_key_headers(key["key"], ws["id"]),
    )
    assert resp.status_code == 403
    assert "member:manage" in resp.json()["detail"]


async def test_garbage_and_revoked_keys_are_rejected(app_client):
    client = app_client
    owner = await register_user(client, "rose@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    resp = await client.get(
        "/api/v1/members",
        headers={"Authorization": "Bearer sk_live_totally-bogus", "X-Workspace-ID": ws["id"]},
    )
    assert resp.status_code == 401

    key = await _create_key(client, headers, "doomed", ["member:read"])
    kh = _key_headers(key["key"], ws["id"])
    assert (await client.get("/api/v1/members", headers=kh)).status_code == 200

    resp = await client.delete(f"/api/v1/api-keys/{key['id']}", headers=headers)
    assert resp.status_code == 204

    resp = await client.get("/api/v1/members", headers=kh)
    assert resp.status_code == 401
    assert resp.json()["detail"] != "missing permission"


async def test_effective_permissions_requires_apikey_read(app_client):
    client = app_client
    owner = await register_user(client, "sam@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    read_only = await _create_key(client, headers, "read-only", ["member:read"])
    resp = await client.get(
        "/api/v1/api-keys/effective-permissions", headers=_key_headers(read_only["key"], ws["id"])
    )
    assert resp.status_code == 403
    assert "apikey:read" in resp.json()["detail"]

    key = await _create_key(client, headers, "key-read", ["apikey:read"])
    resp = await client.get(
        "/api/v1/api-keys/effective-permissions", headers=_key_headers(key["key"], ws["id"])
    )
    assert resp.status_code == 200
    assert "*" in resp.json()["permissions"]


# ------------------------------------------------------------------- seed


async def test_seed_api_key_definitions_stay_within_creator_scope():
    """The seed's declared keys must never exceed the creator's role — the
    same invariant the API enforces at runtime."""
    from src.seed import API_KEYS

    role_by_creator: dict[tuple[str, str], str] = {
        ("acme-corp", "admin@example.com"): "owner",
        ("acme-corp", "user1@example.com"): "editor",
        ("globex", "user1@example.com"): "viewer",
    }
    assert API_KEYS, "seed should define at least one api key"

    for slug, email, name, permissions in API_KEYS:
        role_name = role_by_creator.get((slug, email))
        assert role_name, f"seed key {name} has no known creator role"
        role_perms = set(permissions_for_role(role_name))
        assert set(permissions) <= role_perms or "*" in role_perms, (
            f"seed key {name} grants permissions outside {role_name} scope"
        )


async def test_seed_creates_api_keys(app_client):
    from src.seed import API_KEYS
    from src.seed import main as seed_main

    await seed_main()

    async with SessionFactory() as session:
        from sqlalchemy import select

        from src.models.api_key import ApiKey

        rows = (await session.execute(select(ApiKey))).scalars().all()

    assert len(rows) == len(API_KEYS)
    for slug, email, name, permissions in API_KEYS:
        # resolve the workspace + user ids the seed used
        async with SessionFactory() as session:
            from src.models.workspace import User, Workspace

            ws = (
                await session.execute(select(Workspace).where(Workspace.slug == slug))
            ).scalar_one()
            user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        matches = [k for k in rows if k.workspace_id == ws.id and k.name == name]
        assert matches, f"seed should create api key {name} in {slug}"
        key = matches[0]
        assert key.created_by_user_id == user.id
        assert sorted(key.permissions) == sorted(permissions)
        assert key.key_prefix.startswith("sk_live_")
        assert len(key.key_hash) == 64
