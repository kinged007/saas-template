"""Roles: registry completeness, filtered catalog, create validation, update endpoint."""

import re
from pathlib import Path

import src.core.permissions as perms
from tests.conftest import (
    auth_headers,
    create_workspace,
    register_user,
    ws_headers,
)

ROUTES_DIR = Path(__file__).resolve().parent.parent / "src" / "api" / "routes"


def _guarded_permissions() -> set[str]:
    """Every permission string referenced by route guards, resolved to its value."""
    found: set[str] = set()
    pattern = re.compile(r"require_(?:key_)?permission\((\w+)\)")
    for path in ROUTES_DIR.glob("*.py"):
        for name in pattern.findall(path.read_text()):
            value = getattr(perms, name, None)
            assert value is not None, f"{path.name}: unknown permission constant {name}"
            found.add(value)
    # Constants used indirectly (e.g. jobs' _require_job_access switch).
    for name in ("JOB_READ", "JOB_UPDATE"):
        found.add(getattr(perms, name))
    return found


async def _roles(client, headers) -> list[dict]:
    resp = await client.get("/api/v1/roles", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _role_id(client, headers, name: str) -> str:
    return next(r for r in await _roles(client, headers) if r["name"] == name)["id"]


async def _add_member(client, owner_tokens, ws, email: str, role_name: str):
    roles = await _roles(client, ws_headers(owner_tokens, ws["id"]))
    role = next(r for r in roles if r["name"] == role_name)
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
    return user


# ------------------------------------------------------- registry + catalog


async def test_permission_registry_covers_route_guards():
    guarded = _guarded_permissions()
    assert guarded, "no guarded permissions found — regex drift?"
    assert guarded <= set(perms.PERMISSION_DEFINITIONS), (
        f"route guards missing from registry: {sorted(guarded - set(perms.PERMISSION_DEFINITIONS))}"
    )


async def test_permission_catalog_requires_auth(app_client):
    resp = await app_client.get(
        "/api/v1/roles/permission-catalog", headers={"X-Workspace-ID": "ws-does-not-exist"}
    )
    assert resp.status_code in (401, 403)


async def test_permission_catalog_filtered_to_assignable(app_client):
    client = app_client
    owner = await register_user(client, "cat-owner@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    viewer = await _add_member(client, owner, ws, "cat-viewer@example.com", "viewer")

    owner_catalog = (
        await client.get("/api/v1/roles/permission-catalog", headers=owner_headers)
    ).json()
    assert set(owner_catalog["catalog"]) == set(perms.ALL_PERMISSIONS)
    assert set(owner_catalog["permissions"]) == set(perms.ALL_PERMISSIONS)
    assert not (set(owner_catalog["catalog"]) & set(perms.KEY_ONLY_PERMISSIONS))
    assert not (set(owner_catalog["permissions"]) & set(perms.KEY_ONLY_PERMISSIONS))

    viewer_catalog = (
        await client.get("/api/v1/roles/permission-catalog", headers=ws_headers(viewer, ws["id"]))
    ).json()
    assert set(viewer_catalog["catalog"]) == set(perms.ALL_PERMISSIONS)
    assert set(viewer_catalog["permissions"]) < set(perms.ALL_PERMISSIONS)
    assert "workspace:delete" not in viewer_catalog["permissions"]


# ------------------------------------------------------------------ create


async def test_create_role_rejects_unknown_permission(app_client):
    client = app_client
    owner = await register_user(client, "cr1@example.com")
    ws = await create_workspace(client, owner)
    resp = await client.post(
        "/api/v1/roles",
        json={"name": "ops", "permissions": ["billing:read"]},
        headers=ws_headers(owner, ws["id"]),
    )
    assert resp.status_code == 422


async def test_create_role_rejects_duplicate_name(app_client):
    client = app_client
    owner = await register_user(client, "cr2@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    resp = await client.post(
        "/api/v1/roles", json={"name": "ops", "permissions": []}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/api/v1/roles", json={"name": "ops", "permissions": []}, headers=headers
    )
    assert resp.status_code == 409


async def test_permission_catalog_excludes_legacy_key_only_scope(app_client):
    # A stale role row holding a legacy key-only scope must not resurface it.
    from src.db.session import SessionFactory
    from src.models.workspace import Role

    client = app_client
    owner = await register_user(client, "cat-legacy@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    editor_id = await _role_id(client, headers, "editor")
    async with SessionFactory() as session:
        role = await session.get(Role, editor_id)
        role.permissions = [*role.permissions, "notification:read"]
        await session.commit()
    catalog = (await client.get("/api/v1/roles/permission-catalog", headers=headers)).json()
    assert "notification:read" not in catalog["permissions"]
    assert "notification:read" not in catalog["catalog"]


async def test_create_role_rejects_key_only_permissions(app_client):
    client = app_client
    owner = await register_user(client, "cr-keyonly@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    resp = await client.post(
        "/api/v1/roles",
        json={"name": "ops", "permissions": ["notification:read"]},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    resp = await client.post(
        "/api/v1/roles",
        json={"name": "ops", "permissions": ["member:read", "notification:update"]},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


async def test_create_role_rejects_star(app_client):
    client = app_client
    owner = await register_user(client, "cr3@example.com")
    ws = await create_workspace(client, owner)
    resp = await client.post(
        "/api/v1/roles",
        json={"name": "ops", "permissions": ["*"]},
        headers=ws_headers(owner, ws["id"]),
    )
    assert resp.status_code == 422


async def test_create_role_capped_by_creator_permissions(app_client):
    client = app_client
    owner = await register_user(client, "cr4@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    admin = await _add_member(client, owner, ws, "cr4-admin@example.com", "admin")
    resp = await client.post(
        "/api/v1/roles",
        json={"name": "ops", "permissions": ["workspace:delete"]},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 403
    # ...but the owner (holder of "*") can grant it.
    resp = await client.post(
        "/api/v1/roles",
        json={"name": "ops", "permissions": ["workspace:delete"]},
        headers=owner_headers,
    )
    assert resp.status_code == 201, resp.text


# ------------------------------------------------------------------ update


async def test_update_role(app_client):
    client = app_client
    owner = await register_user(client, "up1@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    created = (
        await client.post(
            "/api/v1/roles",
            json={"name": "ops", "description": "old", "permissions": ["audit:read"]},
            headers=headers,
        )
    ).json()
    resp = await client.patch(
        f"/api/v1/roles/{created['id']}",
        json={
            "name": "operators",
            "description": "new",
            "permissions": ["audit:read", "member:read"],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "operators"
    assert body["description"] == "new"
    assert sorted(body["permissions"]) == ["audit:read", "member:read"]


async def test_update_role_forbidden_without_manage(app_client):
    client = app_client
    owner = await register_user(client, "up2@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    viewer = await _add_member(client, owner, ws, "up2-viewer@example.com", "viewer")
    editor_id = await _role_id(client, owner_headers, "editor")
    resp = await client.patch(
        f"/api/v1/roles/{editor_id}",
        json={"description": "hijacked"},
        headers=ws_headers(viewer, ws["id"]),
    )
    assert resp.status_code == 403


async def test_update_role_cross_workspace_is_404(app_client):
    client = app_client
    owner = await register_user(client, "up3@example.com")
    ws1 = await create_workspace(client, owner, name="One")
    ws2 = await create_workspace(client, owner, name="Two")
    editor_id = await _role_id(client, ws_headers(owner, ws1["id"]), "editor")
    resp = await client.patch(
        f"/api/v1/roles/{editor_id}",
        json={"description": "x"},
        headers=ws_headers(owner, ws2["id"]),
    )
    assert resp.status_code == 404


async def test_update_role_rejects_key_only_permissions(app_client):
    client = app_client
    owner = await register_user(client, "up-keyonly@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    editor_id = await _role_id(client, headers, "editor")
    resp = await client.patch(
        f"/api/v1/roles/{editor_id}",
        json={"permissions": ["member:read", "notification:read"]},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


async def test_update_role_rejects_unknown_permission_and_star(app_client):
    client = app_client
    owner = await register_user(client, "up4@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    editor_id = await _role_id(client, headers, "editor")
    for bad in (["billing:read"], ["*"]):
        resp = await client.patch(
            f"/api/v1/roles/{editor_id}", json={"permissions": bad}, headers=headers
        )
        assert resp.status_code == 422, bad


async def test_update_owner_role_forbidden(app_client):
    client = app_client
    owner = await register_user(client, "up5@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    owner_id = await _role_id(client, headers, "owner")
    resp = await client.patch(
        f"/api/v1/roles/{owner_id}", json={"description": "x"}, headers=headers
    )
    assert resp.status_code == 403


async def test_update_system_role_converts_to_custom(app_client):
    client = app_client
    owner = await register_user(client, "up6@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    editor_id = await _role_id(client, headers, "editor")
    resp = await client.patch(
        f"/api/v1/roles/{editor_id}",
        json={"permissions": ["workspace:read"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["system"] is False


async def test_update_role_noop_keeps_system_flag(app_client):
    client = app_client
    owner = await register_user(client, "up-noop@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    editor_id = await _role_id(client, headers, "editor")
    editor = (await client.get(f"/api/v1/roles/{editor_id}", headers=headers)).json()
    assert editor["system"] is True
    resp = await client.patch(
        f"/api/v1/roles/{editor_id}",
        json={"description": editor["description"], "permissions": editor["permissions"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["system"] is True


async def test_get_role_unknown_and_cross_workspace_is_404(app_client):
    """#192: the lookup raises WorkspaceNotFound for both miss shapes."""
    client = app_client
    owner = await register_user(client, "get404@example.com")
    ws1 = await create_workspace(client, owner, name="One")
    ws2 = await create_workspace(client, owner, name="Two")
    editor_id = await _role_id(client, ws_headers(owner, ws1["id"]), "editor")
    for role_id, ws in (("00000000-0000-0000-0000-000000000000", ws1), (editor_id, ws2)):
        resp = await client.get(f"/api/v1/roles/{role_id}", headers=ws_headers(owner, ws["id"]))
        assert resp.status_code == 404, (role_id, resp.text)
        assert resp.json()["detail"] == "role not found"


async def test_update_role_noop_body_keeps_system_flag(app_client):
    """#193: an empty body and a same-name body are both no-ops, not resets."""
    client = app_client
    owner = await register_user(client, "up-noop-body@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    editor_id = await _role_id(client, headers, "editor")
    for body in ({}, {"name": "editor"}):
        resp = await client.patch(f"/api/v1/roles/{editor_id}", json=body, headers=headers)
        assert resp.status_code == 200, (body, resp.text)
        assert resp.json()["system"] is True, body


async def test_update_role_duplicate_name_conflicts(app_client):
    client = app_client
    owner = await register_user(client, "up7@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    created = (
        await client.post("/api/v1/roles", json={"name": "ops", "permissions": []}, headers=headers)
    ).json()
    resp = await client.patch(
        f"/api/v1/roles/{created['id']}", json={"name": "editor"}, headers=headers
    )
    assert resp.status_code == 409
