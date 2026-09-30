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


async def _add_key_only_to_role(role_id: str, permission: str) -> None:
    """Stale key-only scope on a role row; the catalog intersection must drop it."""
    from src.db.session import SessionFactory
    from src.models.workspace import Role

    async with SessionFactory() as session:
        role = await session.get(Role, role_id)
        assert role is not None, role_id
        role.permissions = [*role.permissions, permission]
        await session.commit()


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
    # Seed the key-only scope before the member joins. accept_invitation stores
    # role_id and copies no permissions, so this way the viewer holds the scope
    # from the moment it joins and the test does not depend on get_membership
    # joining Role live on WorkspaceMember.role_id. The intersection at
    # roles.py:92 is only reachable for a non-owner caller.
    await _add_key_only_to_role(
        await _role_id(client, owner_headers, "viewer"), perms.NOTIFICATION_READ
    )
    viewer = await _add_member(client, owner, ws, "cat-viewer@example.com", "viewer")

    resp = await client.get("/api/v1/roles/permission-catalog", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    owner_catalog = resp.json()
    assert set(owner_catalog["catalog"]) == set(perms.ALL_PERMISSIONS)
    assert set(owner_catalog["permissions"]) == set(perms.ALL_PERMISSIONS)
    assert not (set(owner_catalog["catalog"]) & set(perms.KEY_ONLY_PERMISSIONS))
    assert not (set(owner_catalog["permissions"]) & set(perms.KEY_ONLY_PERMISSIONS))

    resp = await client.get(
        "/api/v1/roles/permission-catalog", headers=ws_headers(viewer, ws["id"])
    )
    assert resp.status_code == 200, resp.text
    viewer_catalog = resp.json()
    assert set(viewer_catalog["catalog"]) == set(perms.ALL_PERMISSIONS)
    assert set(viewer_catalog["permissions"]) < set(perms.ALL_PERMISSIONS)
    assert "workspace:delete" not in viewer_catalog["permissions"]
    # The seed above is what makes these two lines a check: the viewer's own
    # scopes carry a key-only scope, so the intersection must drop it.
    assert not (set(viewer_catalog["catalog"]) & set(perms.KEY_ONLY_PERMISSIONS))
    assert not (set(viewer_catalog["permissions"]) & set(perms.KEY_ONLY_PERMISSIONS))


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


async def test_create_role_strips_padded_name(app_client):
    # A padded name is stored stripped, so it stays reachable as an
    # auto-join target instead of existing under a name nothing matches.
    client = app_client
    owner = await register_user(client, "cr3@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    resp = await client.post(
        "/api/v1/roles", json={"name": "  ops  ", "permissions": []}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "ops"
    assert await _role_id(client, headers, "ops")


async def test_create_role_rejects_blank_name(app_client):
    client = app_client
    owner = await register_user(client, "cr4@example.com")
    ws = await create_workspace(client, owner)
    resp = await client.post(
        "/api/v1/roles",
        json={"name": "   ", "permissions": []},
        headers=ws_headers(owner, ws["id"]),
    )
    assert resp.status_code == 422


async def test_update_role_strips_padded_name(app_client):
    client = app_client
    owner = await register_user(client, "up3@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    created = (
        await client.post("/api/v1/roles", json={"name": "ops", "permissions": []}, headers=headers)
    ).json()
    resp = await client.patch(
        f"/api/v1/roles/{created['id']}", json={"name": "  operators  "}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "operators"
    resp = await client.patch(
        f"/api/v1/roles/{created['id']}", json={"name": "   "}, headers=headers
    )
    assert resp.status_code == 422


async def test_permission_catalog_excludes_legacy_key_only_scope(app_client):
    # A stale role row holding a legacy key-only scope must not resurface it.
    # Read as an editor: the owner holds "*" and short-circuits the intersection.
    client = app_client
    owner = await register_user(client, "cat-legacy@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    await _add_key_only_to_role(await _role_id(client, headers, "editor"), perms.NOTIFICATION_READ)
    editor = await _add_member(client, owner, ws, "cat-legacy-editor@example.com", "editor")
    resp = await client.get(
        "/api/v1/roles/permission-catalog", headers=ws_headers(editor, ws["id"])
    )
    assert resp.status_code == 200, resp.text
    catalog = resp.json()
    assert perms.NOTIFICATION_READ not in catalog["permissions"]
    assert perms.NOTIFICATION_READ not in catalog["catalog"]
    # The editor's own scopes survive the intersection, so this is not an empty response.
    assert set(catalog["permissions"]) == set(perms.permissions_for_role("editor"))


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


# ------------------------------------------------------------------- listing

# 4 system roles + 8 custom = 12, past the default page size of 10.
_CUSTOM_ROLE_NAMES = ["zulu", "alpha", "mike", "bravo", "yankee", "delta", "echo", "foxtrot"]


async def _roles_past_ten(client, prefix: str):
    owner = await register_user(client, f"{prefix}@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    for name in _CUSTOM_ROLE_NAMES:
        resp = await client.post(
            "/api/v1/roles", json={"name": name, "permissions": []}, headers=headers
        )
        assert resp.status_code == 201, resp.text
    return headers


async def test_roles_list_is_not_capped_at_ten(app_client):
    """#258: the full set is retrievable, and the count says how big it is."""
    client = app_client
    headers = await _roles_past_ten(client, "list-cap")
    resp = await client.get("/api/v1/roles", params={"_start": 0, "_end": 100}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["X-Total-Count"] == "12"
    assert len(resp.json()) == 12


async def test_roles_default_order_is_system_first(app_client):
    client = app_client
    headers = await _roles_past_ten(client, "list-order")
    resp = await client.get("/api/v1/roles", params={"_start": 0, "_end": 100}, headers=headers)
    assert resp.status_code == 200, resp.text
    names = [r["name"] for r in resp.json()]
    assert names[:4] == ["owner", "admin", "editor", "viewer"]
    assert names[4:] == sorted(_CUSTOM_ROLE_NAMES)


async def test_roles_client_sort_does_not_split_the_system_block(app_client):
    client = app_client
    headers = await _roles_past_ten(client, "list-sorted")
    resp = await client.get(
        "/api/v1/roles",
        params={"_start": 0, "_end": 100, "sort[]": "name", "order[]": "asc"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert [r["name"] for r in resp.json()][:4] == ["owner", "admin", "editor", "viewer"]


async def test_roles_client_sort_desc_reverses_only_within_the_rank_groups(app_client):
    client = app_client
    headers = await _roles_past_ten(client, "list-sorted-desc")
    resp = await client.get(
        "/api/v1/roles",
        params={"_start": 0, "_end": 100, "sort[]": "name", "order[]": "desc"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    names = [r["name"] for r in resp.json()]
    assert names[:4] == ["owner", "admin", "editor", "viewer"]
    assert names[4:] == sorted(_CUSTOM_ROLE_NAMES, reverse=True)


async def test_roles_paging_tiles_the_set_without_gaps(app_client):
    """Rank + name is a total order, so pages tile the set in that one order.

    The expectation is built here rather than fetched from a full-set request:
    two runs of the same endpoint agree even when the order is not total.
    """
    client = app_client
    headers = await _roles_past_ten(client, "list-page")
    paged: list[dict] = []
    for start in (0, 5, 10):
        resp = await client.get(
            "/api/v1/roles", params={"_start": start, "_end": start + 5}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        paged += resp.json()
    expected = ["owner", "admin", "editor", "viewer", *sorted(_CUSTOM_ROLE_NAMES)]
    assert [r["name"] for r in paged] == expected
    assert len({r["id"] for r in paged}) == 12


# ------------------------------------------------------ case-insensitive names
# #259: a name that only differs in case from an existing one (system or custom)
# would render as a second, indistinguishable row in listings and selects.


async def test_create_role_rejects_case_variant_of_existing_name(app_client):
    client = app_client
    owner = await register_user(client, "ci1@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    before = len(await _roles(client, headers))
    for name in ("Admin", "ADMIN", "owner", "Owner", "Editor", "viewer"):
        resp = await client.post(
            "/api/v1/roles", json={"name": name, "permissions": []}, headers=headers
        )
        assert resp.status_code == 409, (name, resp.text)
    assert len(await _roles(client, headers)) == before


async def test_create_role_rejects_duplicate_name_ignoring_case(app_client):
    client = app_client
    owner = await register_user(client, "ci2@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    resp = await client.post(
        "/api/v1/roles", json={"name": "Billing", "permissions": []}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    for name in ("billing", "BILLING", "EDITOR"):
        resp = await client.post(
            "/api/v1/roles", json={"name": name, "permissions": []}, headers=headers
        )
        assert resp.status_code == 409, (name, resp.text)
    # The conflict names the stored role, not the casing that was requested.
    resp = await client.post(
        "/api/v1/roles", json={"name": "billing", "permissions": []}, headers=headers
    )
    assert resp.json()["detail"] == "a role named 'Billing' already exists"


async def test_create_role_allows_similar_name(app_client):
    """Only whole-name case variants conflict — a prefix or substring stays free."""
    client = app_client
    owner = await register_user(client, "ci3@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    for name in ("administrator", "Admin Team", "Owner Ops"):
        resp = await client.post(
            "/api/v1/roles", json={"name": name, "permissions": []}, headers=headers
        )
        assert resp.status_code == 201, (name, resp.text)


async def test_update_role_rejects_case_variant_of_existing_name(app_client):
    client = app_client
    owner = await register_user(client, "ci4@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    created = (
        await client.post("/api/v1/roles", json={"name": "ops", "permissions": []}, headers=headers)
    ).json()
    for name in ("Editor", "OWNER"):
        resp = await client.patch(
            f"/api/v1/roles/{created['id']}", json={"name": name}, headers=headers
        )
        assert resp.status_code == 409, (name, resp.text)
    # A change of case on the role's own name is not a conflict.
    resp = await client.patch(
        f"/api/v1/roles/{created['id']}", json={"name": "OPS"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "OPS"


async def test_case_variant_is_free_in_another_workspace(app_client):
    """The predicate stays workspace-scoped: the gate is per workspace, not global."""
    client = app_client
    owner = await register_user(client, "ci5@example.com")
    ws1 = await create_workspace(client, owner, name="Acme One")
    ws2 = await create_workspace(client, owner, name="Acme Two")
    billing = await client.post(
        "/api/v1/roles",
        json={"name": "Billing", "permissions": []},
        headers=ws_headers(owner, ws1["id"]),
    )
    assert billing.status_code == 201, billing.text
    resp = await client.post(
        "/api/v1/roles",
        json={"name": "BILLING", "permissions": []},
        headers=ws_headers(owner, ws2["id"]),
    )
    assert resp.status_code == 201, resp.text


async def test_legacy_case_duplicate_pair_conflicts_instead_of_500(app_client):
    """A workspace predating the fix can hold `admin` + `Admin`; both writers 409.

    The case-insensitive predicate matches both rows, so the existence check must
    not assume a single match — an unhandled MultipleResultsFound here is a 500
    on a path the contract promises as 409.
    """
    from src.db.session import SessionFactory
    from src.models.workspace import Role

    client = app_client
    owner = await register_user(client, "ci6@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    async with SessionFactory() as session:
        session.add(
            Role(
                workspace_id=ws["id"],
                name="Admin",
                description=None,
                permissions=[],
                system=False,
            )
        )
        await session.commit()
    created = (
        await client.post("/api/v1/roles", json={"name": "ops", "permissions": []}, headers=headers)
    ).json()
    resp = await client.post(
        "/api/v1/roles", json={"name": "ADMIN", "permissions": []}, headers=headers
    )
    assert resp.status_code == 409, resp.text
    resp = await client.patch(
        f"/api/v1/roles/{created['id']}", json={"name": "admin"}, headers=headers
    )
    assert resp.status_code == 409, resp.text


async def test_non_ascii_case_variant_is_not_a_conflict_on_sqlite(app_client):
    """Records the `lower()` split: SQLite does not fold every non-ASCII letter.

    `Élève` and `élève` are two rows on SQLite, which is what the suite runs on,
    and one on Postgres, where `lower()` is Unicode-aware. Recorded, not endorsed.
    """
    client = app_client
    owner = await register_user(client, "ci7@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    resp = await client.post(
        "/api/v1/roles", json={"name": "Élève", "permissions": []}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/api/v1/roles", json={"name": "élève", "permissions": []}, headers=headers
    )
    assert resp.status_code == 201, resp.text
