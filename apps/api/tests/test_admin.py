"""Admin surface: superuser-only user lookup, disable, workspace list, audit, flags."""

from __future__ import annotations

from datetime import UTC, datetime

from src.db.session import SessionFactory
from src.models.workspace import User, Workspace
from tests.conftest import auth_headers, create_workspace, login, register_user, ws_headers


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
    # LIKE wildcards match literally: "%" appears in no email.
    wild = await client.get("/api/v1/admin/users?search=%", headers=auth_headers(tokens))
    assert wild.status_code == 200, wild.text
    assert wild.json() == []
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
    row = next(w for w in resp.json() if w["id"] == ws["id"])
    assert row["member_count"] == 1

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


async def test_admin_flags_reject_malformed_workspace_id(app_client):
    """The path param reaches db.get(Workspace, ...) — a bad id must be a 422, not a 500."""
    client, tokens = await _superuser_client(app_client)

    resp = await client.patch(
        "/api/v1/admin/workspaces/not-a-uuid/flags",
        json={"flags": {"invites_enabled": False}},
        headers=auth_headers(tokens),
    )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"][0]
    assert detail["type"] == "uuid_parsing", resp.text
    assert detail["loc"] == ["path", "workspace_id"], resp.text


async def test_admin_audit_cross_workspace(app_client):
    import asyncio

    client, tokens = await _superuser_client(app_client)
    ws = await create_workspace(client, tokens, "Widget Co")

    actions: list[str] = []
    scoped = None
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

    # enriched names for readable rows
    scoped = await client.get(
        "/api/v1/admin/audit",
        params={"workspace_id": ws["id"]},
        headers=auth_headers(tokens),
    )
    assert scoped.status_code == 200, scoped.text
    assert {e["workspace_id"] for e in scoped.json()} == {ws["id"]}
    assert scoped.json()[0]["workspace_name"] == "Widget Co"

    # cross-field search: workspace name, user email, action, exact ids
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    for term in ("Widget Co", "root@", "workspace.created", me.json()["id"], ws["id"]):
        found = await client.get(
            "/api/v1/admin/audit", params={"q": term}, headers=auth_headers(tokens)
        )
        assert found.status_code == 200, (term, found.text)
        assert int(found.headers["x-total-count"]) >= 1, term
    empty = await client.get(
        "/api/v1/admin/audit", params={"q": "zzz-no-such-thing"}, headers=auth_headers(tokens)
    )
    assert empty.json() == [] and empty.headers["x-total-count"] == "0"

    # workspace-scoped search: user email, action, actor id (same ?q= contract)
    wsh = ws_headers(tokens, ws["id"])
    for term in ("root@", "workspace.created", me.json()["id"]):
        found = await client.get("/api/v1/audit", params={"q": term}, headers=wsh)
        assert found.status_code == 200, (term, found.text)
        assert int(found.headers["x-total-count"]) >= 1, term
    assert found.json()[0]["actor_email"] == "root@example.com"
    empty = await client.get("/api/v1/audit", params={"q": "zzz-no-such-thing"}, headers=wsh)
    assert empty.json() == [] and empty.headers["x-total-count"] == "0"


async def test_admin_malformed_id_404(app_client):
    # The workspace case is not here: that path param is annotated UUID, so a
    # malformed id is a 422 (test_admin_flags_reject_malformed_workspace_id).
    # 404-on-malformed only exists to avoid an existence oracle, and the admin
    # surface is superuser-only — nothing to hide from a caller who can already
    # list every workspace.
    client, tokens = await _superuser_client(app_client)
    for method, url, kwargs in [
        ("get", "/api/v1/admin/users/not-a-uuid", {}),
        ("patch", "/api/v1/admin/users/not-a-uuid", {"json": {"is_active": False}}),
    ]:
        resp = await client.request(method, url, headers=auth_headers(tokens), **kwargs)
        assert resp.status_code == 404, (method, url, resp.text)


async def test_admin_lists_default_created_desc_with_tiebreaker(app_client):
    client, tokens = await _superuser_client(app_client)
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))

    # Arrange the tie instead of hoping for it: registration and workspace
    # creation run provisioning workflows, so their rows can land seconds apart
    # and the id tiebreaker would never fire. Ids ascend in insertion order, so
    # a created_at DESC sort without the tiebreaker returns this pair as-is
    # rather than reversed.
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    tied: dict[str, list] = {
        "/api/v1/admin/users": [
            User(
                id=f"00000000-0000-4000-8000-00000000000{i}",
                email=email,
                display_name=email,
                created_at=stamp,
                updated_at=stamp,
            )
            for i, email in enumerate(("aaa@example.com", "zzz@example.com"), start=1)
        ],
        "/api/v1/admin/workspaces": [
            Workspace(
                id=f"00000000-0000-4000-8000-00000000000{i}",
                name=name,
                slug=f"tied-{i}",
                created_by_user_id=me.json()["id"],
                created_at=stamp,
                updated_at=stamp,
            )
            for i, name in enumerate(("Acme", "Globex"), start=1)
        ],
    }
    async with SessionFactory() as session:
        session.add_all(tied["/api/v1/admin/users"] + tied["/api/v1/admin/workspaces"])
        await session.commit()

    # No sort param => created_at DESC, id DESC. The tied rows share created_at,
    # so only the id term decides their order.
    for path, rows in tied.items():
        resp = await client.get(path, headers=auth_headers(tokens))
        assert resp.status_code == 200, resp.text
        ids = {r.id for r in rows}
        listed = [r for r in resp.json() if r["id"] in ids]
        assert len(listed) == len(rows), path
        assert len({r["created_at"] for r in listed}) == 1, f"{path}: no created_at tie"
        assert [r["id"] for r in listed] == sorted(ids, reverse=True), path

    # An explicit sort still overrides the server default.
    resp = await client.get(
        "/api/v1/admin/users?sort[]=email&order[]=asc", headers=auth_headers(tokens)
    )
    assert resp.status_code == 200, resp.text
    emails = [u["email"] for u in resp.json()]
    assert emails == sorted(emails), emails
    assert "aaa@example.com" in emails and "zzz@example.com" in emails


async def test_admin_self_reenable_200(app_client):
    client, tokens = await _superuser_client(app_client)
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    resp = await client.patch(
        f"/api/v1/admin/users/{me.json()['id']}",
        json={"is_active": True},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is True
