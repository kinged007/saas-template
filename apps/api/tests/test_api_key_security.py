"""Security tests for API key authentication and authorization.

Covers, end to end over the HTTP API:
  * creation caps — a key can never be minted with a permission its creator
    does not hold (every escalation vector, wildcard, non-member callers);
    a key minted BY another key is additionally capped by the minting key's
    own permission list
  * read access — a key can read exactly the resources its permission list
    grants, and nothing else
  * edit access — PATCH/POST mutations require the matching permission
  * delete access — DELETE mutations require the matching permission
  * workspace scoping — a key minted in one workspace can never touch another
  * user scoping — a key reaches only its creator's own notifications, the
    property that makes the key-only scopes safe to offer
  * ownership scoping — users see and manage ONLY their own keys; neither
    listing nor revoking ever crosses the creator boundary, not even for
    wildcard-permission admins
  * authentication hygiene — garbage/revoked keys, zero-permission keys,
    and proof that key permissions never inherit the creator's role
  * session-only surfaces — 2FA, sessions, the password, the personal data
    export, and the deployment-admin flag all refuse a key
"""

import pytest
from sqlalchemy import select

from src.core.permissions import ALL_PERMISSIONS, JOB_READ, JOB_UPDATE, permissions_for_role
from src.db.session import SessionFactory
from src.models.api_key import ApiKey
from src.models.jobs import JobDefinition
from src.services.api_keys import ApiKeyService
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


async def _create_key(client, headers, name, permissions, usage_quota=None):
    body = {"name": name, "permissions": permissions}
    if usage_quota is not None:
        body["usage_quota"] = usage_quota
    resp = await client.post("/api/v1/api-keys", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _key_headers(raw: str, ws_id: str) -> dict:
    return {"Authorization": f"Bearer {raw}", "X-Workspace-ID": ws_id}


async def _user_id(client, tokens) -> str:
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.status_code == 200, me.text
    return me.json()["id"]


async def _seed_runs(workspace_id: str) -> dict[str, str]:
    """A global run plus two workspace runs, inserted directly so the tests do
    not depend on job provisioning."""
    import uuid

    from src.core.dates import now_utc
    from src.models.jobs import JobDefinition, JobRun

    ids: dict[str, str] = {}
    async with SessionFactory() as session:
        definition = JobDefinition(
            id=str(uuid.uuid4()),
            key="test.seeded",
            workspace_id=workspace_id,
            name="Seeded",
            cron_schedule="0 0 * * *",
        )
        session.add(definition)
        ids["definition"] = definition.id
        for name, ws_id, definition_id in (
            ("global", None, str(uuid.uuid4())),
            ("workspace", workspace_id, definition.id),
            # A second own-workspace run, under its own definition_id so the
            # runs route of `definition` still counts exactly one.
            ("workspace_2", workspace_id, str(uuid.uuid4())),
        ):
            run = JobRun(
                id=str(uuid.uuid4()),
                definition_id=definition_id,
                workspace_id=ws_id,
                status="success",
                scheduled_at=now_utc(),
            )
            session.add(run)
            ids[name] = run.id
        await session.commit()
    return ids


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
        ("notification:read", "GET", "/api/v1/notifications", None),  # key-only scope
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


@pytest.mark.parametrize("grant", [["workspace:read"], ["workspace:read", "member:read"]])
async def test_workspaces_list_reports_the_keys_grant_for_key_principals(app_client, grant):
    """GET /workspaces for a key reports the key's own grant, like /auth/me.

    The two endpoints must agree on the shape: `permissions` is what this
    principal can do, not the creator's role. `[]` is a real grant, never a
    fallback to the role.
    """
    client = app_client
    owner = await register_user(client, "ws-grant@example.com")
    ws = await create_workspace(client, owner, "Ws Grant Inc")
    key = await _create_key(client, ws_headers(owner, ws["id"]), "ws-granted", grant)

    resp = await client.get("/api/v1/workspaces", headers=_key_headers(key["key"], ws["id"]))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1
    assert resp.json()[0]["permissions"] == sorted(grant)

    me_key = await client.get("/api/v1/auth/me", headers=_key_headers(key["key"], ws["id"]))
    assert me_key.status_code == 200, me_key.text
    assert me_key.json()["workspaces"][0]["permissions"] == resp.json()[0]["permissions"]
    assert me_key.json()["permissions"] == resp.json()[0]["permissions"]


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

    # member:update — role change
    manage_key = await _create_key(client, headers, "member-manage", ["member:update"])
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

    # role:create — create a custom role
    role_key = await _create_key(client, headers, "role-manage", ["role:create"])
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

    # notification:update — mark read
    nid = await _insert_notification(ws["id"], owner_id)
    nkey = await _create_key(client, headers, "notif-ack", ["notification:update"])
    nkh = _key_headers(nkey["key"], ws["id"])
    resp = await client.patch(
        f"/api/v1/notifications/{nid}", json={"acknowledged": True}, headers=nkh
    )
    assert resp.status_code == 200, resp.text
    resp = await client.patch(
        f"/api/v1/notifications/{nid}", json={"acknowledged": True}, headers=read_kh
    )
    assert resp.status_code == 403

    # key minted by the editor (who has no member:update) cannot change roles
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

    # member:delete — remove a member
    manage_key = await _create_key(client, headers, "member-manage", ["member:delete"])
    manage_kh = _key_headers(manage_key["key"], ws["id"])
    resp = await client.delete(f"/api/v1/members/{eve_membership}", headers=manage_kh)
    assert resp.status_code == 204
    assert (
        await client.delete(f"/api/v1/members/{eve_membership}", headers=read_kh)
    ).status_code == 403

    # apikey:delete — revoke another key
    victim = await _create_key(client, headers, "victim", ["member:read"])
    revoke_key = await _create_key(client, headers, "revoker", ["apikey:delete"])
    revoke_kh = _key_headers(revoke_key["key"], ws["id"])
    resp = await client.delete(f"/api/v1/api-keys/{victim['id']}", headers=revoke_kh)
    assert resp.status_code == 204
    keys = await client.get("/api/v1/api-keys", headers=headers)
    assert next(k for k in keys.json() if k["id"] == victim["id"])["revoked_at"] is not None
    resp = await client.delete(f"/api/v1/api-keys/{victim['id']}", headers=read_kh)
    assert resp.status_code == 403

    # notification delete — gated on notification:update for keys
    nid = await _insert_notification(ws["id"], owner_id)
    nkey = await _create_key(client, headers, "notif-ack", ["notification:update"])
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
    # Live workspace with a cross-workspace key: 403 (exists, not permitted).
    resp = await client.delete(
        f"/api/v1/workspaces/{del_ws['id']}", headers=_key_headers(read_key["key"], del_ws["id"])
    )
    assert resp.status_code == 403
    resp = await client.delete(
        f"/api/v1/workspaces/{del_ws['id']}", headers=_key_headers(del_key["key"], del_ws["id"])
    )
    assert resp.status_code == 204
    resp = await client.get(
        f"/api/v1/workspaces/{del_ws['id']}",
        headers=ws_headers(owner, del_ws["id"]),
    )
    assert resp.status_code == 404

    # Deleted workspace: require_existing_workspace 404s before the key-scope
    # check (consistent with session auth); 403 applies to live workspaces only.
    resp = await client.delete(
        f"/api/v1/workspaces/{del_ws['id']}", headers=_key_headers(read_key["key"], del_ws["id"])
    )
    assert resp.status_code == 404


# ------------------------------------------------------- ownership scoping


async def test_users_only_see_their_own_api_keys(app_client):
    """The reported leak: user1 must never see keys created by the admin."""
    client = app_client
    owner = await register_user(client, "tina@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    editor = await _add_member(client, owner_headers, ws["id"], "ursula@example.com", "editor")

    admin_a = await _create_key(client, owner_headers, "admin-key-a", ["member:read"])
    admin_b = await _create_key(client, owner_headers, "admin-key-b", ["role:read"])
    editor_key = await _create_key(
        client, ws_headers(editor, ws["id"]), "editor-key", ["member:read"]
    )

    seen_by_owner = await client.get("/api/v1/api-keys", headers=owner_headers)
    assert seen_by_owner.status_code == 200
    assert seen_by_owner.headers["X-Total-Count"] == "2"
    owner_ids = {k["id"] for k in seen_by_owner.json()}
    assert owner_ids == {admin_a["id"], admin_b["id"]}
    assert editor_key["id"] not in owner_ids
    assert "editor-key" not in {k["name"] for k in seen_by_owner.json()}

    seen_by_editor = await client.get("/api/v1/api-keys", headers=ws_headers(editor, ws["id"]))
    assert seen_by_editor.status_code == 200
    assert seen_by_editor.headers["X-Total-Count"] == "1"
    editor_ids = {k["id"] for k in seen_by_editor.json()}
    assert editor_ids == {editor_key["id"]}
    assert {admin_a["id"], admin_b["id"]}.isdisjoint(editor_ids)
    assert {"admin-key-a", "admin-key-b"}.isdisjoint({k["name"] for k in seen_by_editor.json()})


async def test_runners_reapply_the_owner_predicate(app_client):
    """The runners enforce the scope themselves: a bare select(ApiKey) still
    cannot reach another user's keys, or the same user's keys elsewhere."""
    client = app_client
    owner = await register_user(client, "sven@example.com")
    owner_id = await _user_id(client, owner)
    ws = await create_workspace(client, owner, name="One")
    other_ws = await create_workspace(client, owner, name="Two")
    owner_headers = ws_headers(owner, ws["id"])

    editor = await _add_member(client, owner_headers, ws["id"], "teresa@example.com", "editor")
    editor_id = await _user_id(client, editor)

    owner_key = await _create_key(client, owner_headers, "owner-key", ["member:read"])
    elsewhere = await _create_key(
        client, ws_headers(owner, other_ws["id"]), "elsewhere", ["member:read"]
    )
    editor_key = await _create_key(
        client, ws_headers(editor, ws["id"]), "editor-key", ["member:read"]
    )

    async with SessionFactory() as session:
        service = ApiKeyService(session)
        rows = await service.list_for_user(ws["id"], owner_id, select(ApiKey))
        assert {k.id for k in rows} == {owner_key["id"]}
        assert await service.count_for_user(ws["id"], owner_id, select(ApiKey)) == 1

        # ... and the scope of the other user is equally narrow
        rows = await service.list_for_user(ws["id"], editor_id, select(ApiKey))
        assert {k.id for k in rows} == {editor_key["id"]}
        assert await service.count_for_user(ws["id"], editor_id, select(ApiKey)) == 1

        # a statement scoped to somebody else narrows to empty rather than
        # borrowing theirs: the re-applied predicate ANDs, it never replaces
        other_owner = select(ApiKey).where(ApiKey.created_by_user_id == editor_id)
        other_ws_stmt = select(ApiKey).where(ApiKey.workspace_id == other_ws["id"])
        already = select(ApiKey).where(
            ApiKey.workspace_id == ws["id"], ApiKey.created_by_user_id == owner_id
        )

        async def run_ids(stmt: object) -> set[str]:
            rows = await service.list_for_user(ws["id"], owner_id, stmt)
            return {k.id for k in rows}

        assert await run_ids(other_owner) == set()
        assert await service.count_for_user(ws["id"], owner_id, other_owner) == 0
        assert await run_ids(other_ws_stmt) == set()
        assert await service.count_for_user(ws["id"], owner_id, other_ws_stmt) == 0
        # a statement that already carries the caller's own scope is unchanged
        assert await run_ids(already) == {owner_key["id"]}

    # the unscoped statement really does reach every key — the runners narrowed it
    async with SessionFactory() as session:
        all_rows = list((await session.execute(select(ApiKey))).scalars().all())
    assert {k.id for k in all_rows} == {owner_key["id"], editor_key["id"], elsewhere["id"]}


async def test_user_cannot_revoke_anothers_api_key(app_client):
    """Revoking someone else's key 404s — even for wildcard-permission admins."""
    client = app_client
    owner = await register_user(client, "vera@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    editor = await _add_member(client, owner_headers, ws["id"], "walt@example.com", "editor")
    editor_headers = ws_headers(editor, ws["id"])

    admin_key = await _create_key(client, owner_headers, "admins", ["member:read"])
    editor_key = await _create_key(client, editor_headers, "editors", ["member:read"])

    # editor has apikey:delete (passes the permission gate) but not ownership → 404
    resp = await client.delete(f"/api/v1/api-keys/{admin_key['id']}", headers=editor_headers)
    assert resp.status_code == 404, resp.text

    # the reverse direction: an "*" admin still cannot revoke the editor's key
    resp = await client.delete(f"/api/v1/api-keys/{editor_key['id']}", headers=owner_headers)
    assert resp.status_code == 404, resp.text

    # neither key was actually revoked — both still appear unrevoked to their owners
    owner_listing = (await client.get("/api/v1/api-keys", headers=owner_headers)).json()
    editor_listing = (await client.get("/api/v1/api-keys", headers=editor_headers)).json()
    assert next(k for k in owner_listing if k["id"] == admin_key["id"])["revoked_at"] is None
    assert next(k for k in editor_listing if k["id"] == editor_key["id"])["revoked_at"] is None

    # each user revokes their own key without trouble
    assert (
        await client.delete(f"/api/v1/api-keys/{admin_key['id']}", headers=owner_headers)
    ).status_code == 204
    assert (
        await client.delete(f"/api/v1/api-keys/{editor_key['id']}", headers=editor_headers)
    ).status_code == 204


async def test_user_cannot_set_quota_on_anothers_api_key(app_client):
    """PATCH quota on someone else's key 404s and leaves the quota untouched."""
    client = app_client
    owner = await register_user(client, "xavier@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    editor = await _add_member(client, owner_headers, ws["id"], "yara@example.com", "editor")
    editor_headers = ws_headers(editor, ws["id"])

    admin_key = await _create_key(client, owner_headers, "admins", ["member:read"])

    resp = await client.patch(
        f"/api/v1/api-keys/{admin_key['id']}",
        json={"usage_quota": 5},
        headers=editor_headers,
    )
    assert resp.status_code == 404, resp.text

    listing = (await client.get("/api/v1/api-keys", headers=owner_headers)).json()
    assert next(k for k in listing if k["id"] == admin_key["id"])["usage_quota"] is None

    resp = await client.patch(
        f"/api/v1/api-keys/{admin_key['id']}",
        json={"usage_quota": 5},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["usage_quota"] == 5


async def test_key_minted_by_a_key_is_capped_by_the_minting_key(app_client):
    """A key can never mint a new key carrying a permission it doesn't hold,
    even though its human owner's role is broader."""
    client = app_client
    owner = await register_user(client, "xena@example.com")  # owner role: "*"
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    automation = await _create_key(
        client, owner_headers, "automation", ["apikey:create", "apikey:delete", "apikey:read"]
    )
    auto_kh = _key_headers(automation["key"], ws["id"])

    # owner's role includes everything via "*", but the minting key does not:
    # requesting a permission outside the key's own list must be rejected
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "escalated", "permissions": ["member:update"]},
        headers=auto_kh,
    )
    assert resp.status_code == 403, resp.text
    assert "member:update" in resp.json()["detail"]

    # wildcard escalation via the same route
    resp = await client.post(
        "/api/v1/api-keys", json={"name": "wild", "permissions": ["*"]}, headers=auto_kh
    )
    assert resp.status_code == 403

    # within its own list it may still mint
    child = await _create_key(client, auto_kh, "child", ["apikey:read"])
    assert child["permissions"] == ["apikey:read"]

    # a "*" key acts with its owner's full authority and may grant broadly
    superkey = await _create_key(client, owner_headers, "superkey", ["*"])
    broad = await _create_key(
        client, _key_headers(superkey["key"], ws["id"]), "broad", ["member:update"]
    )
    assert broad["permissions"] == ["member:update"]


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


# ------------------------------------------------- notification scoping


async def test_key_reaches_only_its_creators_notifications(app_client):
    """The user-scoping guarantee behind `KEY_ONLY_PERMISSIONS`.

    `core.permissions` offers `notification:read` / `notification:update` to any
    member with `apikey:read` on the strength of the scopes being user-scoped:
    a key resolves to its creator's `User` and reaches nothing that creator
    could not reach with a session. That is a claim about reach, so it is
    asserted as one — which scopes the endpoint *offers* is a different
    statement. Drop the `user_id` predicate from the notification queries and
    this is what goes red."""
    client = app_client
    owner = await register_user(client, "notif-owner@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    alice = await _add_member(client, owner_headers, ws["id"], "alice@example.com", "editor")
    alice_headers = ws_headers(alice, ws["id"])
    bob = await _add_member(client, owner_headers, ws["id"], "bob@example.com", "editor")
    alice_id = await _user_id(client, alice)
    bob_id = await _user_id(client, bob)

    mine = await _insert_notification(ws["id"], alice_id, "Alice's alert")
    theirs = await _insert_notification(ws["id"], bob_id, "Bob's alert")

    key = await _create_key(
        client, alice_headers, "alice-notifs", ["notification:read", "notification:update"]
    )
    kh = _key_headers(key["key"], ws["id"])

    # the list is filtered per user, not per workspace. Alice also has the
    # notifications her own membership produced, so the assertion is about
    # whose rows these are, not about how many there are.
    listed = await client.get("/api/v1/notifications", headers=kh)
    assert listed.status_code == 200, listed.text
    ids = {n["id"] for n in listed.json()}
    assert mine in ids
    assert theirs not in ids

    # ... and neither ack nor delete reaches the other member's row by id
    for method, url, body in [
        ("patch", f"/api/v1/notifications/{theirs}", {"acknowledged": True}),
        ("delete", f"/api/v1/notifications/{theirs}", None),
    ]:
        resp = await client.request(method, url, json=body, headers=kh)
        assert resp.status_code == 404, (method, url, resp.status_code, resp.text)

    # The refusals left Bob's notification untouched, and Bob's own session
    # still reaches it — so the 404s above are the user predicate, not a row
    # that was missing or already acted on.
    bob_headers = ws_headers(bob, ws["id"])
    bob_listed = await client.get("/api/v1/notifications", headers=bob_headers)
    assert theirs in {n["id"] for n in bob_listed.json()}
    resp = await client.patch(
        f"/api/v1/notifications/{theirs}", json={"acknowledged": True}, headers=bob_headers
    )
    assert resp.status_code == 200, resp.text

    # Alice's key still reaches her own notification on both verbs
    for method, url, body, status in [
        ("patch", f"/api/v1/notifications/{mine}", {"acknowledged": True}, 200),
        ("delete", f"/api/v1/notifications/{mine}", None, 204),
    ]:
        resp = await client.request(method, url, json=body, headers=kh)
        assert resp.status_code == status, (method, url, resp.status_code, resp.text)


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

    # the owner's session can change roles (role has member:update)...
    resp = await client.patch(
        f"/api/v1/members/{eve_membership}",
        json={"role_id": viewer_role},
        headers=headers,
    )
    assert resp.status_code == 200

    # ...but a key minted by the same owner without member:update cannot
    key = await _create_key(client, headers, "read-only", ["member:read"])
    resp = await client.patch(
        f"/api/v1/members/{eve_membership}",
        json={"role_id": viewer_role},
        headers=_key_headers(key["key"], ws["id"]),
    )
    assert resp.status_code == 403
    assert "member:update" in resp.json()["detail"]


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


# --------------------------------------------- deployment-wide power


async def test_superuser_key_cannot_reach_superuser_routes(app_client):
    """Keys never inherit deployment-wide power, even from a superuser.

    Regression test for #93. It enumerates every deployment-wide surface,
    not just the routes a given diff touched, because the invariant is
    "a key never carries deployment-wide power" — asserting it only where
    the fix landed would pass while the leak survives elsewhere."""
    client = app_client
    root = await register_user(client, "root@example.com")  # SUPERADMIN_EMAIL
    me = await client.get("/api/v1/auth/me", headers=auth_headers(root))
    assert me.json()["is_superuser"] is True
    ws = await create_workspace(client, root)
    key = await _create_key(client, ws_headers(root, ws["id"]), "root-key", ["*"])
    key_headers = _key_headers(key["key"], ws["id"])
    victim_id = await _user_id(client, await register_user(client, "victim@example.com"))
    runs = await _seed_runs(ws["id"])

    surfaces = [
        ("get", "/api/v1/admin/users"),
        ("get", "/api/v1/admin/workspaces"),
        ("get", "/api/v1/jobs/global"),
        ("get", f"/api/v1/users/{victim_id}/export"),
        ("delete", f"/api/v1/users/{victim_id}"),
        # The same rule, reached through routes that resolve their own
        # superuser check (`_require_run_access`) rather than through
        # `require_superuser`.
        ("get", f"/api/v1/jobs/runs/{runs['global']}"),
        ("get", f"/api/v1/jobs/runs/{runs['global']}/logs"),
    ]
    for method, url in surfaces:
        resp = await client.request(method, url, headers=key_headers)
        assert resp.status_code == 403, (method, url, resp.status_code, resp.text)
        # One kind of denial, one message: every path above is the
        # deployment-admin gate, so a key caller is told the same thing
        # whichever route it probed.
        assert resp.json()["detail"] == (
            "deployment administration is not available to API keys"
        ), (method, url, resp.text)

    # /auth/me stays readable by a key — it is the key's own identity — but
    # reports the creator's deployment-admin flag as false, so the field
    # reads the principal's power rather than the raw user column.
    me_key = await client.get("/api/v1/auth/me", headers=key_headers)
    assert me_key.status_code == 200, me_key.text
    assert me_key.json()["is_superuser"] is False, me_key.text

    # The profile projection's superuser bypass is off for a key, so it
    # falls back to co-membership and finds none (404, not a 403 leak).
    resp = await client.get(f"/api/v1/users/{victim_id}/profile", headers=key_headers)
    assert resp.status_code == 404, resp.text

    # The same path names the missing privilege to a session caller, without
    # revealing whether that session would otherwise be a superuser.
    plain = await register_user(client, "plain@example.com")
    resp = await client.get("/api/v1/admin/users", headers=auth_headers(plain))
    assert resp.status_code == 403, resp.status_code
    assert resp.json()["detail"] == "superuser access required", resp.text

    # The superuser's own session still reaches all of them.
    session = await client.get("/api/v1/admin/users", headers=auth_headers(root))
    assert session.status_code == 200, session.text
    export = await client.get(f"/api/v1/users/{victim_id}/export", headers=auth_headers(root))
    assert export.status_code == 200, export.text
    profile = await client.get(f"/api/v1/users/{victim_id}/profile", headers=auth_headers(root))
    assert profile.status_code == 200, profile.text

    # The superuser's own session reaches all of them, from the same list
    # the key loop uses. Only the delete answers 204.
    for method, url in surfaces:
        resp = await client.request(method, url, headers=auth_headers(root))
        assert resp.status_code == (204 if method == "delete" else 200), (
            method,
            url,
            resp.status_code,
            resp.text,
        )
    me_session = await client.get("/api/v1/auth/me", headers=auth_headers(root))
    assert me_session.json()["is_superuser"] is True, me_session.text


async def test_auth_me_reports_the_principals_scope_not_the_owners(app_client):
    """/auth/me answers for the caller, so a key never learns the owner's inventory.

    A workspace-scoped key used to be handed every workspace its creator
    belonged to, each with its role and permission set. That leaked another
    workspace's id — the one value every route behind it refuses to hand out
    ("api key is not scoped to this workspace").
    """
    client = app_client
    owner = await register_user(client, "scope-owner@example.com")
    ws = await create_workspace(client, owner, "Scoped Inc")
    other_ws = await create_workspace(client, owner, "Other Inc")
    key = await _create_key(client, ws_headers(owner, ws["id"]), "scoped", ["member:read"])

    me_key = await client.get("/api/v1/auth/me", headers=_key_headers(key["key"], ws["id"]))
    assert me_key.status_code == 200, me_key.text
    assert [w["id"] for w in me_key.json()["workspaces"]] == [ws["id"]]

    # The owner's own session still sees the whole inventory, and its
    # top-level union is still the union of the roles it holds there.
    me_owner = await client.get("/api/v1/auth/me", headers=auth_headers(owner))
    assert me_owner.status_code == 200, me_owner.text
    assert {w["id"] for w in me_owner.json()["workspaces"]} == {ws["id"], other_ws["id"]}
    assert set(me_owner.json()["permissions"]) == {
        p for w in me_owner.json()["workspaces"] for p in w["permissions"]
    }

    # The key's top-level `permissions` is its own grant — the same list
    # deps.py authorizes it on — and never the creator's role, which for an
    # owner is the wildcard.
    assert me_key.json()["permissions"] == sorted(key["permissions"])
    assert "*" not in me_key.json()["permissions"]


@pytest.mark.parametrize("grant", [[], ["member:read"]])
async def test_auth_me_reports_the_keys_own_grant_not_the_owners_role(app_client, grant):
    """A key's authority is the grant it was minted with, so `/me` reports it.

    `[]` is the case a truthiness check gets wrong: an empty grant is a real
    grant, not a missing one, and must not fall back to the creator's role.
    """
    client = app_client
    owner = await register_user(client, "grant@example.com")
    ws = await create_workspace(client, owner, "Granted Inc")
    key = await _create_key(client, ws_headers(owner, ws["id"]), "granted", grant)

    me_key = await client.get("/api/v1/auth/me", headers=_key_headers(key["key"], ws["id"]))
    assert me_key.status_code == 200, me_key.text
    assert me_key.json()["permissions"] == sorted(grant)
    assert me_key.json()["is_superuser"] is False

    # Same user, same endpoint: the creator's session still answers with its
    # own role union, so the narrowing belongs to the principal, not the route.
    me_owner = await client.get("/api/v1/auth/me", headers=auth_headers(owner))
    assert me_owner.status_code == 200, me_owner.text
    assert "*" in me_owner.json()["permissions"]
    assert me_key.json()["permissions"] != me_owner.json()["permissions"]


@pytest.mark.parametrize("grant", [[], ["member:read"]])
async def test_auth_me_narrows_workspace_permissions_to_the_keys_grant(app_client, grant):
    """For a key principal, `workspaces[].permissions` is the key's own grant.

    The nested field used to carry the creator's role set, so a client
    reading it (like the web's `active?.permissions ?? identity?.permissions`)
    got a capability the key does not have. `[]` pins the same truthiness
    trap as the top-level fix: an empty grant stays `[]`, not the role.
    """
    client = app_client
    owner = await register_user(client, "narrow@example.com")
    ws = await create_workspace(client, owner, "Narrow Inc")
    key = await _create_key(client, ws_headers(owner, ws["id"]), "narrowed", grant)

    me_key = await client.get("/api/v1/auth/me", headers=_key_headers(key["key"], ws["id"]))
    assert me_key.status_code == 200, me_key.text
    body = me_key.json()
    assert len(body["workspaces"]) == 1
    assert body["workspaces"][0]["permissions"] == sorted(grant)
    assert body["workspaces"][0]["permissions"] == body["permissions"]

    me_owner = await client.get("/api/v1/auth/me", headers=auth_headers(owner))
    assert me_owner.status_code == 200, me_owner.text
    assert "*" in me_owner.json()["workspaces"][0]["permissions"]
    assert body["workspaces"][0]["permissions"] != me_owner.json()["workspaces"][0]["permissions"]


async def test_auth_me_passes_a_wildcard_grant_through_verbatim(app_client):
    """A wildcard key is the highest-stakes pass-through: `['*']` reaches both
    the nested entry and the top-level field unfiltered. No inequality-vs-owner
    assertion here — an owner's role is also `*`, which is why the equality
    parametrization above skips this grant."""
    client = app_client
    owner = await register_user(client, "wild@example.com")
    ws = await create_workspace(client, owner, "Wild Grant Inc")
    key = await _create_key(client, ws_headers(owner, ws["id"]), "wild", ["*"])

    me_key = await client.get("/api/v1/auth/me", headers=_key_headers(key["key"], ws["id"]))
    assert me_key.status_code == 200, me_key.text
    body = me_key.json()
    assert len(body["workspaces"]) == 1
    assert body["workspaces"][0]["permissions"] == ["*"]
    assert body["permissions"] == ["*"]


async def test_auth_me_drops_a_keys_grant_when_its_membership_is_suspended(app_client):
    """`permissions` is what the gate authorizes on, and the gate also checks
    the membership: a key whose creator's membership is not active gets no
    workspaces, so it must get no permissions either."""
    client = app_client
    owner = await register_user(client, "susp-owner@example.com")
    ws = await create_workspace(client, owner, "Susp Grant Inc")
    owner_headers = ws_headers(owner, ws["id"])
    # The key's creator is the admin, not the owner: the owner cannot be
    # suspended (nor suspend themselves), and a key belongs to whoever minted
    # it, so the membership under test has to be the second one.
    admin = await _add_member(client, owner_headers, ws["id"], "susp-admin@example.com", "admin")
    key = await _create_key(client, ws_headers(admin, ws["id"]), "granted", ["member:read"])

    membership_id = next(
        m["membership_id"]
        for m in (await client.get("/api/v1/members", headers=owner_headers)).json()
        if m["email"] == "susp-admin@example.com"
    )
    suspended = await client.post(f"/api/v1/members/{membership_id}/suspend", headers=owner_headers)
    assert suspended.status_code == 200, suspended.text

    me_key = await client.get("/api/v1/auth/me", headers=_key_headers(key["key"], ws["id"]))
    assert me_key.status_code == 200, me_key.text
    assert me_key.json()["workspaces"] == []
    assert me_key.json()["permissions"] == []


async def test_job_run_access_uses_the_keys_own_permissions(app_client):
    """A run is authorized against the key's own permission list and its own
    workspace — never the creator's role, and never deployment-wide."""
    client = app_client
    owner = await register_user(client, "run-owner@example.com")
    ws = await create_workspace(client, owner, "Run Owner Inc")
    headers = ws_headers(owner, ws["id"])
    runs = await _seed_runs(ws["id"])
    other = await register_user(client, "run-other@example.com")
    foreign_ws = await create_workspace(client, other, "Run Other Inc")
    foreign = (await _seed_runs(foreign_ws["id"]))["workspace"]

    # A key without jobs:read is refused even though its creator holds the
    # permission through the workspace owner role, and the refusal is the same
    # for both of the key's own runs — the answer must not depend on which
    # own-workspace id was asked for.
    narrow = await _create_key(client, headers, "no-jobs", ["member:read"])
    narrow_headers = _key_headers(narrow["key"], ws["id"])
    own_refusals = set()
    for run_id in (runs["workspace"], runs["workspace_2"]):
        resp = await client.get(f"/api/v1/jobs/runs/{run_id}", headers=narrow_headers)
        own_refusals.add((resp.status_code, resp.json().get("detail")))
    assert own_refusals == {(403, f"missing permission: {JOB_READ}")}, own_refusals

    # A foreign X-Workspace-ID header does not widen the key's own scope.
    resp = await client.get(
        f"/api/v1/jobs/runs/{foreign}", headers=_key_headers(narrow["key"], foreign_ws["id"])
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "deployment administration is not available to API keys"

    viewer = await _create_key(client, headers, "jobs-read", ["jobs:read"])
    viewer_headers = _key_headers(viewer["key"], ws["id"])
    ok = await client.get(f"/api/v1/jobs/runs/{runs['workspace']}", headers=viewer_headers)
    assert ok.status_code == 200, ok.text
    logs = await client.get(f"/api/v1/jobs/runs/{runs['workspace']}/logs", headers=viewer_headers)
    assert logs.status_code == 200, logs.text

    # ... but the same key never reaches a global run or another workspace, and
    # one refusal covers both.
    for url in [
        f"/api/v1/jobs/runs/{runs['global']}",
        f"/api/v1/jobs/runs/{runs['global']}/logs",
        f"/api/v1/jobs/runs/{foreign}",
    ]:
        resp = await client.get(url, headers=viewer_headers)
        assert resp.status_code == 403, (url, resp.text)
        assert resp.json()["detail"] == (
            "deployment administration is not available to API keys"
        ), url

    # usage_quota = 0 is refused at the counter: the conditional UPDATE's
    # `usage_count < usage_quota` would be `0 < 0`, so the key the mint would
    # hand back could never authenticate. No key is returned at all.
    refused = await client.post(
        "/api/v1/api-keys",
        json={"name": "quota-zero", "permissions": [JOB_READ], "usage_quota": 0},
        headers=headers,
    )
    assert refused.status_code == 422, refused.text

    # A key-authorized hit is metered like any other key route: every read and
    # write route spends one unit and reports what is left. Regression test for
    # #311 — the key branch of _require_run_access and _require_job_access used
    # to return without record_key_use. Each key carries only what its own
    # route needs — a GET is gated on jobs:read, a write on jobs:update — so
    # the second request's refusal can only be the quota's doing.
    for method, url, key_name, charged_status, body, refused_body in [
        ("get", f"/api/v1/jobs/runs/{runs['workspace']}", "quota-run", 200, None, None),
        ("get", f"/api/v1/jobs/runs/{runs['workspace']}/logs", "quota-logs", 200, None, None),
        ("get", f"/api/v1/jobs/{runs['definition']}", "quota-definition", 200, None, None),
        ("get", f"/api/v1/jobs/{runs['definition']}/runs", "quota-runs", 200, None, None),
        (
            "patch",
            f"/api/v1/jobs/{runs['definition']}",
            "quota-patch",
            200,
            {"cron_schedule": "30 4 * * *"},
            {"cron_schedule": "45 5 * * *"},
        ),
        ("post", f"/api/v1/jobs/{runs['definition']}/execute", "quota-execute", 201, {}, {}),
    ]:
        capped = await _create_key(
            client,
            headers,
            key_name,
            [JOB_READ if method == "get" else JOB_UPDATE],
            usage_quota=1,
        )
        capped_headers = _key_headers(capped["key"], ws["id"])
        first = await client.request(method, url, json=body, headers=capped_headers)
        assert first.status_code == charged_status, (url, first.text)
        assert first.headers["X-API-Key-Quota"] == "1", url
        assert first.headers["X-API-Key-Remaining"] == "0", url
        if url.endswith("/runs"):
            # the charge must not clobber the list route's own header
            assert first.headers["X-Total-Count"] == "1", url

        # quota exhausted → 403, and the refusal does not spend again: the
        # charge happens in the access helper before the handler body, and a
        # refused call neither increments nor commits.
        second = await client.request(method, url, json=refused_body, headers=capped_headers)
        assert second.status_code == 403, (url, second.text)
        assert "quota" in second.json()["detail"].lower(), url
        async with SessionFactory() as db:
            row = await db.get(ApiKey, capped["id"])
            assert row.usage_count == 1, (url, "a refused request must not spend a unit")

    # The refused PATCH never reached the write: the definition still holds
    # the schedule the charged request set.
    after = await client.get(f"/api/v1/jobs/{runs['definition']}", headers=auth_headers(owner))
    assert after.json()["cron_schedule"] == "30 4 * * *", after.text


async def test_key_cannot_probe_global_run_existence(app_client):
    """A run id that resolves to nothing must not answer differently for a key.

    The run routes used to fetch the run first, so a key got 403 on an
    existing global run and 404 on an id that matched none — a run-existence
    oracle on a surface it can never read. Three states a key may not read
    (global run, another workspace's run, no such run) must all be the one
    deployment-admin refusal. Regression test for #856.
    """
    import uuid

    client = app_client
    owner = await register_user(client, "probe-owner@example.com")
    ws = await create_workspace(client, owner, "Probe Inc")
    runs = await _seed_runs(ws["id"])
    other = await register_user(client, "probe-other@example.com")
    foreign_ws = await create_workspace(client, other, "Probe Other Inc")
    foreign = (await _seed_runs(foreign_ws["id"]))["workspace"]
    key = await _create_key(client, ws_headers(owner, ws["id"]), "prober", [JOB_READ])
    kh = _key_headers(key["key"], ws["id"])

    missing = str(uuid.uuid4())
    for url in [
        f"/api/v1/jobs/runs/{runs['global']}",
        f"/api/v1/jobs/runs/{runs['global']}/logs",
        f"/api/v1/jobs/runs/{foreign}",
        f"/api/v1/jobs/runs/{foreign}/logs",
        f"/api/v1/jobs/runs/{missing}",
        f"/api/v1/jobs/runs/{missing}/logs",
    ]:
        resp = await client.get(url, headers=kh)
        assert resp.status_code == 403, (url, resp.status_code, resp.text)
        assert resp.json()["detail"] == (
            "deployment administration is not available to API keys"
        ), url

    # The same key still reads the run it is entitled to, so the collapsed
    # answer is not the route refusing everything.
    ok = await client.get(f"/api/v1/jobs/runs/{runs['workspace']}", headers=kh)
    assert ok.status_code == 200, ok.text

    # A session caller is unaffected: a missing run is still a 404 for it.
    missing_session = await client.get(f"/api/v1/jobs/runs/{missing}", headers=auth_headers(owner))
    assert missing_session.status_code == 404, missing_session.text
    global_session = await client.get(
        f"/api/v1/jobs/runs/{runs['global']}", headers=auth_headers(owner)
    )
    assert global_session.status_code == 403, global_session.text


async def test_one_quota_unit_cannot_be_spent_twice(app_client):
    """Two callers that read the counter before either writes must not both
    spend the last unit — the quota check and the increment are one
    statement, not a read followed by a write."""
    from src.models.api_key import ApiKey
    from src.services.api_keys import ApiKeyService

    client = app_client
    owner = await register_user(client, "quota-race@example.com")
    ws = await create_workspace(client, owner, "Quota Race Inc")
    capped = await _create_key(
        client, ws_headers(owner, ws["id"]), "race", ["member:read"], usage_quota=1
    )

    async with SessionFactory() as first, SessionFactory() as second:
        # Both sessions read the key while usage_count is still 0 — the
        # interleaving that used to let both commit usage_count = 1.
        one, two = await first.get(ApiKey, capped["id"]), await second.get(ApiKey, capped["id"])
        assert (one.usage_count, two.usage_count) == (0, 0)

        assert await ApiKeyService(first).record_use(one) is True
        assert await ApiKeyService(second).record_use(two) is False

    async with SessionFactory() as verify:
        row = await verify.get(ApiKey, capped["id"])
        assert row.usage_count == 1, "a refused charge must not be spent"


async def _seed_definition(workspace_id: str | None, key: str = "test.echo") -> str:
    """A definition row owned by `workspace_id` (None for a global one),
    bypassing async provisioning."""
    import uuid

    async with SessionFactory() as session:
        definition = JobDefinition(
            id=str(uuid.uuid4()),
            key=key,
            workspace_id=workspace_id,
            name="Echo",
            description="",
            cron_schedule="0 6 * * *",
            params_schema={},
            params={},
            enabled=False,
        )
        session.add(definition)
        await session.commit()
        return definition.id


async def test_job_definition_access_uses_the_keys_own_permissions(app_client):
    """A definition is authorized against the key's own permission list and its
    own workspace — a foreign-workspace key gets the deployment-admin refusal,
    the same one it gets for a global definition, and never the definition."""
    client = app_client
    owner = await register_user(client, "jobdef-owner@example.com")
    ws = await create_workspace(client, owner, "Jobdef Owner Inc")
    headers = ws_headers(owner, ws["id"])
    definition_id = await _seed_definition(ws["id"])
    other = await register_user(client, "jobdef-other@example.com")
    foreign_ws = await create_workspace(client, other, "Jobdef Other Inc")
    foreign_id = await _seed_definition(foreign_ws["id"])

    # A key scoped to another workspace learns nothing about this definition,
    # whichever workspace header it carries.
    foreign_headers = ws_headers(other, foreign_ws["id"])
    for header_ws in (ws["id"], foreign_ws["id"]):
        key = await _create_key(client, foreign_headers, "jobdef", [JOB_READ])
        resp = await client.get(
            f"/api/v1/jobs/{definition_id}", headers=_key_headers(key["key"], header_ws)
        )
        assert resp.status_code == 403, (header_ws, resp.status_code, resp.text)
        assert resp.json()["detail"] == (
            "deployment administration is not available to API keys"
        ), header_ws

    # The owner's own key still reads its own definition, and not the other one.
    own = await _create_key(client, headers, "jobdef-own", [JOB_READ])
    ok = await client.get(
        f"/api/v1/jobs/{definition_id}", headers=_key_headers(own["key"], ws["id"])
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["id"] == definition_id
    resp = await client.get(
        f"/api/v1/jobs/{foreign_id}", headers=_key_headers(own["key"], ws["id"])
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "deployment administration is not available to API keys"


async def test_key_cannot_probe_definition_existence(app_client):
    """A definition id that resolves to nothing must not answer differently for
    a key, on any of the four definition routes.

    The route bodies used to resolve the definition first and raise
    `404 "job not found"` on a miss, while `_require_job_access` answered a
    global definition with the deployment-admin 403 and another workspace's
    with a 404 — three states a key may not read, three answers, so the pair
    told the key which state produced it. All three must be the one refusal,
    exactly as the run routes do it. Regression test for #1033.
    """
    import uuid

    client = app_client
    owner = await register_user(client, "defprobe-owner@example.com")
    ws = await create_workspace(client, owner, "Def Probe Inc")
    entitled = await _seed_definition(ws["id"])
    global_id = await _seed_definition(None)
    other = await register_user(client, "defprobe-other@example.com")
    foreign_ws = await create_workspace(client, other, "Def Probe Other Inc")
    foreign = await _seed_definition(foreign_ws["id"])
    key = await _create_key(
        client, ws_headers(owner, ws["id"]), "def-prober", [JOB_READ, JOB_UPDATE], usage_quota=50
    )
    kh = _key_headers(key["key"], ws["id"])

    missing = str(uuid.uuid4())
    answers = set()
    for definition_id in (global_id, foreign, missing):
        for method, url, body in [
            ("get", f"/api/v1/jobs/{definition_id}", None),
            ("patch", f"/api/v1/jobs/{definition_id}", {"cron_schedule": "30 4 * * *"}),
            ("post", f"/api/v1/jobs/{definition_id}/execute", {}),
            ("get", f"/api/v1/jobs/{definition_id}/runs", None),
        ]:
            resp = await client.request(method, url, json=body, headers=kh)
            answers.add((resp.status_code, resp.json().get("detail")))
            # A refusal carries no second signal: the quota headers and the
            # list route's X-Total-Count are set only on an authorizing branch.
            # These four asserts cannot fail today — Starlette builds a fresh
            # response when a route raises, so what was written to the
            # injected Response is discarded. They document the contract and
            # would catch a future route that raises after setting them; the
            # `usage_count` asserts below are the ones that detect a charge on
            # the refusal path.
            for header in (
                "X-API-Key-Quota",
                "X-API-Key-Remaining",
                "X-API-Key-Window-Reset",
                "X-Total-Count",
            ):
                assert header not in resp.headers, (url, header)

    assert answers == {(403, "deployment administration is not available to API keys")}, answers

    # Twelve refusals must not spend a unit: the row may show only what the
    # four entitled calls below charge.
    async with SessionFactory() as db:
        row = await db.get(ApiKey, key["id"])
        assert (row.usage_quota, row.usage_count) == (50, 0), (row.usage_quota, row.usage_count)

    # The same key still reads, edits, runs and lists runs for the definition
    # it is entitled to, so the collapsed answer is not the routes refusing
    # everything.
    ok = await client.get(f"/api/v1/jobs/{entitled}", headers=kh)
    assert ok.status_code == 200, ok.text
    assert ok.json()["id"] == entitled
    edited = await client.patch(
        f"/api/v1/jobs/{entitled}", json={"cron_schedule": "45 5 * * *"}, headers=kh
    )
    assert edited.status_code == 200, edited.text
    executed = await client.post(f"/api/v1/jobs/{entitled}/execute", json={}, headers=kh)
    assert executed.status_code == 201, executed.text
    listed = await client.get(f"/api/v1/jobs/{entitled}/runs", headers=kh)
    assert listed.status_code == 200, listed.text

    # ...four authorized calls, four units, whatever the refusals did.
    async with SessionFactory() as db:
        row = await db.get(ApiKey, key["id"])
        assert row.usage_count == 4, row.usage_count

    # A session caller is unaffected: a missing definition is still a 404, and
    # a global one still the superuser gate.
    missing_session = await client.get(f"/api/v1/jobs/{missing}", headers=auth_headers(owner))
    assert missing_session.status_code == 404, missing_session.text
    global_session = await client.get(f"/api/v1/jobs/{global_id}", headers=auth_headers(owner))
    assert global_session.status_code == 403, global_session.text


async def test_permission_refusal_stays_distinct_from_the_deployment_admin_refusal(app_client):
    """The one answer a key may still be told apart is the permission it lacks
    inside its own workspace, and nothing else.

    `test_key_cannot_probe_definition_existence` pins the three states a key
    may never read — global, another workspace's, no such id — as one
    deployment-admin refusal. Inside the key's own workspace the answer is
    deliberately different: `403 "missing permission: jobs:read"` (or
    `jobs:update`), the string `require_permission` returns on every other key
    route, naming the actionable fix. A key scoped to the workspace is
    entitled to the existence of a definition id inside its own workspace, not
    to the definition's contents, so the residual existence channel inside it
    is the accepted consequence, not a gap to close; what must not happen is
    that either branch changes unnoticed. Regression test for #1118.
    """
    import uuid

    client = app_client
    owner = await register_user(client, "split-owner@example.com")
    ws = await create_workspace(client, owner, "Split Inc")
    headers = ws_headers(owner, ws["id"])
    own_a = await _seed_definition(ws["id"])
    own_b = await _seed_definition(ws["id"], key="test.echo.second")
    global_id = await _seed_definition(None)
    other = await register_user(client, "split-other@example.com")
    foreign_ws = await create_workspace(client, other, "Split Other Inc")
    foreign = await _seed_definition(foreign_ws["id"])
    missing = str(uuid.uuid4())
    writer = await _create_key(client, headers, "split-writer", [JOB_UPDATE])
    wh = _key_headers(writer["key"], ws["id"])
    reader = await _create_key(client, headers, "split-reader", [JOB_READ])
    rh = _key_headers(reader["key"], ws["id"])

    # Own workspace: the answer names the permission the route needs, and is
    # the same string for both own ids — it does not depend on which of them
    # the caller asked for.
    own_refusals = set()
    for definition_id in (own_a, own_b):
        for method, url, body, key_headers, required in [
            ("get", f"/api/v1/jobs/{definition_id}", None, wh, JOB_READ),
            ("get", f"/api/v1/jobs/{definition_id}/runs", None, wh, JOB_READ),
            (
                "patch",
                f"/api/v1/jobs/{definition_id}",
                {"cron_schedule": "30 4 * * *"},
                rh,
                JOB_UPDATE,
            ),
            ("post", f"/api/v1/jobs/{definition_id}/execute", {}, rh, JOB_UPDATE),
        ]:
            resp = await client.request(method, url, json=body, headers=key_headers)
            assert resp.status_code == 403, (url, resp.text)
            own_refusals.add((required, resp.json()["detail"]))
    assert own_refusals == {
        (JOB_READ, f"missing permission: {JOB_READ}"),
        (JOB_UPDATE, f"missing permission: {JOB_UPDATE}"),
    }, own_refusals

    # Everything else a key may not read keeps the single deployment-admin
    # answer on all four routes, for either key.
    for key_headers in (wh, rh):
        for definition_id in (global_id, foreign, missing):
            for method, url, body in [
                ("get", f"/api/v1/jobs/{definition_id}", None),
                ("patch", f"/api/v1/jobs/{definition_id}", {"cron_schedule": "30 4 * * *"}),
                ("post", f"/api/v1/jobs/{definition_id}/execute", {}),
                ("get", f"/api/v1/jobs/{definition_id}/runs", None),
            ]:
                resp = await client.request(method, url, json=body, headers=key_headers)
                assert (resp.status_code, resp.json()["detail"]) == (
                    403,
                    "deployment administration is not available to API keys",
                ), (url, resp.text)

    # The entitled side still answers, on both sides of the split: this is two
    # refusals drawn in the right place, not the routes refusing everything.
    read = await client.get(f"/api/v1/jobs/{own_a}", headers=rh)
    assert read.status_code == 200, read.text
    edited = await client.patch(
        f"/api/v1/jobs/{own_b}", json={"cron_schedule": "45 5 * * *"}, headers=wh
    )
    assert edited.status_code == 200, edited.text
    executed = await client.post(f"/api/v1/jobs/{own_a}/execute", json={}, headers=wh)
    assert executed.status_code == 201, executed.text


async def test_key_cannot_touch_two_factor(app_client):
    """No 2FA surface is reachable by a key, not just enrolment.

    Backup codes stay valid logins for the account and no permission list
    covers them, so 2FA is session-only as a feature. `2fa/disable` and
    `2fa/backup-codes` re-verify the password, which a key holder does not
    have — both send the owner's *correct* password here, so the 403 proves
    the gate stopped them, not the credential check."""
    client = app_client
    owner = await register_user(client, "totp-owner@example.com")
    ws = await create_workspace(client, owner, "Totp Owner Inc")
    key = await _create_key(client, ws_headers(owner, ws["id"]), "no-2fa", ["member:read"])
    key_headers = _key_headers(key["key"], ws["id"])

    for method, url, body in [
        ("get", "/api/v1/auth/2fa/status", None),
        ("post", "/api/v1/auth/2fa/setup", None),
        ("post", "/api/v1/auth/2fa/enable", {"setup_token": "x", "code": "000000"}),
        ("post", "/api/v1/auth/2fa/disable", {"password": "Password123!"}),
        ("post", "/api/v1/auth/2fa/backup-codes", {"password": "Password123!"}),
    ]:
        resp = await client.request(method, url, json=body, headers=key_headers)
        assert resp.status_code == 403, (url, resp.status_code, resp.text)

    # The owner's own session can still enrol; the refusals left 2FA off.
    resp = await client.post("/api/v1/auth/2fa/setup", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    state = await client.get("/api/v1/auth/2fa/status", headers=auth_headers(owner))
    assert state.json() == {"enabled": False}, state.text


async def test_key_cannot_export_its_creator_data(app_client):
    """Self-service export is a session capability, like /users/{id}/export.

    The bare key header (no X-Workspace-ID) is deliberate: the route takes no
    workspace scoping, so the missing gate — not workspace scoping — is the
    entire defect."""
    client = app_client
    owner = await register_user(client, "export-owner@example.com")
    ws = await create_workspace(client, owner, "Export Owner Inc")
    key = await _create_key(client, ws_headers(owner, ws["id"]), "no-export", ["member:read"])

    resp = await client.get("/api/v1/me/export", headers={"Authorization": f"Bearer {key['key']}"})
    assert resp.status_code == 403, resp.text

    resp = await client.get("/api/v1/me/export", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["id"] == await _user_id(client, owner)


async def test_key_cannot_write_its_creator_profile_or_delete_the_account(app_client):
    """The rest of the /me write family is a session concept too.

    `DELETE /me` is the sharp edge: for an OAuth-registered user
    (`password_hash is None`) the password confirmation never runs, so any key
    the user ever minted could destroy the account.
    """
    client = app_client
    owner = await register_user(client, "profile-owner@example.com")
    ws = await create_workspace(client, owner, "Profile Owner Inc")
    key = await _create_key(client, ws_headers(owner, ws["id"]), "no-profile", ["member:read"])
    key_headers = {"Authorization": f"Bearer {key['key']}"}

    for method, url, body in [
        ("put", "/api/v1/me/profile", {"display_name": "Hacked"}),
        ("patch", "/api/v1/me/profile", {"bio": "Hacked"}),
        ("delete", "/api/v1/me", {"password": "Password123!", "confirm": "DELETE"}),
    ]:
        resp = await client.request(method, url, json=body, headers=key_headers)
        assert resp.status_code == 403, (method, url, resp.status_code, resp.text)

    # Reading the profile with a key, and writing it as a session, still work.
    assert (await client.get("/api/v1/me/profile", headers=key_headers)).status_code == 200
    resp = await client.patch(
        "/api/v1/me/profile", json={"bio": "Mine"}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text


async def test_key_cannot_manage_sessions_or_password(app_client):
    """Sessions and the password are a session concept; a key carries none.

    This passes before and after the change — it is the guard that deleting
    auth.py's private gate did not silently un-gate the six routes that used
    to call it."""
    client = app_client
    owner = await register_user(client, "session-owner@example.com")
    ws = await create_workspace(client, owner, "Session Owner Inc")
    key = await _create_key(client, ws_headers(owner, ws["id"]), "no-sessions", ["member:read"])
    key_headers = _key_headers(key["key"], ws["id"])
    runs = await _seed_runs(ws["id"])

    for method, url, body in [
        ("get", "/api/v1/auth/sessions", None),
        ("delete", "/api/v1/auth/sessions", None),
        # A global run id the owner never owned: the session gate refuses
        # before the lookup, so no session row is needed for the 403.
        ("delete", f"/api/v1/auth/sessions/{runs['global']}", None),
        (
            "post",
            "/api/v1/auth/change-password",
            {"current_password": "Password123!", "new_password": "Password456!"},
        ),
    ]:
        resp = await client.request(method, url, json=body, headers=key_headers)
        assert resp.status_code == 403, (url, resp.status_code, resp.text)

    # The owner's own session still lists its sessions, and still changes
    # its password.
    resp = await client.get("/api/v1/auth/sessions", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Password123!", "new_password": "Password456!"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 204, resp.text


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

    from src.core.permissions import KEY_ONLY_PERMISSIONS

    for slug, email, name, permissions in API_KEYS:
        role_name = role_by_creator.get((slug, email))
        assert role_name, f"seed key {name} has no known creator role"
        role_perms = set(permissions_for_role(role_name))
        # Key-only scopes (notifications) may ride on any member's key.
        capped = set(permissions) - set(KEY_ONLY_PERMISSIONS)
        assert capped <= role_perms or "*" in role_perms, (
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


async def test_api_key_writer_stores_alphabetical_deduplicated_grant(app_client):
    """Issue #1570: the sole writer of ApiKey.permissions. The /auth/me comment
    that stored order and /workspaces' sorted() agree rests on this."""
    client = app_client
    owner = await register_user(client, "grant-writer@example.com")
    ws = await create_workspace(client, owner)
    # Unsorted input with a duplicate: the writer stores sorted and deduped.
    key = await _create_key(
        client,
        ws_headers(owner, ws["id"]),
        "grant-writer",
        ["member:read", "audit:read", "member:read"],
    )
    assert key["permissions"] == ["audit:read", "member:read"]
    # The invariant is the column, not the response: re-read the persisted row.
    async with SessionFactory() as session:
        row = await session.get(ApiKey, key["id"])
        assert row is not None
        assert row.permissions == ["audit:read", "member:read"]


async def test_auth_me_key_grant_keeps_stored_order_not_alphabetical(app_client):
    """Issue #1570: the key branch of /auth/me reports the stored grant in its
    own order, like the session branch reports a role's list — not a re-sort."""
    client = app_client
    owner = await register_user(client, "grant-order@example.com")
    ws = await create_workspace(client, owner)
    key = await _create_key(
        client, ws_headers(owner, ws["id"]), "grant-order", ["member:read", "audit:read"]
    )

    stored = ["member:read", "audit:read", "member:read", "workspace:update"]
    async with SessionFactory() as session:
        row = (
            await session.execute(select(ApiKey).where(ApiKey.name == "grant-order"))
        ).scalar_one()
        row.permissions = stored
        await session.commit()

    me = await client.get("/api/v1/auth/me", headers=_key_headers(key["key"], ws["id"]))
    assert me.status_code == 200, me.text
    # Same set, stored order, duplicate collapsed once.
    assert me.json()["permissions"] == ["member:read", "audit:read", "workspace:update"]
    assert sorted(me.json()["permissions"]) == sorted(set(stored))
