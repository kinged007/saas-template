"""Roles: registry completeness, filtered catalog, create validation, update endpoint."""

import re
from pathlib import Path

import pytest

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


async def _membership_id(client, owner_tokens, ws, email: str) -> str:
    members = await client.get("/api/v1/members", headers=ws_headers(owner_tokens, ws["id"]))
    return next(m for m in members.json() if m["email"] == email)["membership_id"]


async def _seed_legacy_case_role(
    workspace_id: str, name: str = "Owner", *, permissions: list[str] | None = None
) -> str:
    """Insert a case-variant `Owner`/`Admin` row #328 stopped new writes from
    creating; return its id. `_check_name_free` still refuses these names."""
    from src.db.session import SessionFactory
    from src.models.workspace import Role

    async with SessionFactory() as session:
        role = Role(
            workspace_id=workspace_id,
            name=name,
            description=None,
            permissions=[] if permissions is None else permissions,
            system=False,
        )
        session.add(role)
        await session.commit()
        return role.id


async def _rename_seeded_role(workspace_id: str, name: str, new_name: str) -> None:
    """Rewrite a seeded row's name out of band, as pre-#328 data spells it."""
    from sqlalchemy import select

    from src.db.session import SessionFactory
    from src.models.workspace import Role

    async with SessionFactory() as session:
        role = await session.scalar(
            select(Role).where(Role.workspace_id == workspace_id, Role.name == name)
        )
        assert role is not None, name
        role.name = new_name
        await session.commit()


async def _add_member_holding_role(
    client, owner_tokens, ws, email: str, role_id: str
) -> tuple[dict, str]:
    """Invite a member as viewer, then repoint their role_id at `role_id`.

    A legacy case-variant row can no longer be invited to or assigned through
    the API, so a member holding one only exists the way it existed in
    production: an out-of-band `role_id` write.
    """
    from src.db.session import SessionFactory
    from src.models.workspace import WorkspaceMember

    user = await _add_member(client, owner_tokens, ws, email, "viewer")
    membership_id = await _membership_id(client, owner_tokens, ws, email)
    async with SessionFactory() as session:
        member = await session.get(WorkspaceMember, membership_id)
        member.role_id = role_id
        await session.commit()
    return user, membership_id


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


async def test_permission_catalog_handler_refuses_suspended_member(app_client):
    """#300: the handler's own membership lookup must skip suspended rows, so
    the endpoint it reads as authorizing cannot be reached by a suspended
    caller even when a route guard is bypassed."""
    from fastapi import HTTPException

    from src.api.routes.roles import permission_catalog
    from src.db.session import SessionFactory
    from src.models.workspace import User

    client = app_client
    owner = await register_user(client, "cat-susp-owner@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    admin = await _add_member(client, owner, ws, "cat-susp-admin@example.com", "admin")
    member_id = next(
        m
        for m in (await client.get("/api/v1/members", headers=owner_headers)).json()
        if m["email"] == "cat-susp-admin@example.com"
    )["membership_id"]
    admin_id = (await client.get("/api/v1/auth/me", headers=auth_headers(admin))).json()["id"]
    suspended = await client.post(f"/api/v1/members/{member_id}/suspend", headers=owner_headers)
    assert suspended.status_code == 200, suspended.text

    async with SessionFactory() as session:
        user = await session.get(User, admin_id)
        with pytest.raises(HTTPException) as excinfo:
            await permission_catalog(workspace_id=ws["id"], user=user, db=session)
    assert excinfo.value.status_code == 403
    # End to end the route guard refuses them first.
    refused = await client.get(
        "/api/v1/roles/permission-catalog", headers=ws_headers(admin, ws["id"])
    )
    assert refused.status_code == 403, refused.text


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


async def test_suspended_actor_is_capped_on_role_writes(app_client):
    """A suspended actor is capped as if unauthenticated, not by its own role.

    The role-capping sites resolve the actor's membership with `get_membership`,
    which reads active rows only; a suspended row therefore reads as "no actor
    cap" and every requested permission is denied. The same actor, active, must
    still be able to write — otherwise a refusal for everyone would satisfy the
    deny half.
    """
    from sqlalchemy import select  # noqa: E402

    from src.db.session import SessionFactory
    from src.models.workspace import Role, WorkspaceMember
    from src.services.auth import AuthService
    from src.services.workspaces import WorkspaceForbidden, WorkspaceService

    client = app_client
    owner = await register_user(client, "cap-owner@example.com")
    ws = await create_workspace(client, owner)
    await register_user(client, "cap-admin@example.com")
    owner_headers = ws_headers(owner, ws["id"])

    async with SessionFactory() as session:
        service = WorkspaceService(session)
        admin_user = await AuthService(session).get_by_email("cap-admin@example.com")
        assert admin_user is not None, "cap-admin@example.com was not registered"
        role_ids = {
            name: await _role_id(client, owner_headers, name) for name in ("admin", "editor")
        }
        member = WorkspaceMember(
            workspace_id=ws["id"],
            user_id=admin_user.id,
            role_id=role_ids["admin"],
            status="active",
        )
        session.add(member)
        await session.commit()

        # `member:read` is in the admin role's permission set, so the writes
        # below only fail when something other than the suspension stops them.
        created = await service.create_custom_role(
            ws["id"], name="ops", description=None, permissions=["member:read"], actor=admin_user
        )
        assert created.name == "ops"
        # A different payload than the suspended call: `update_role` returns
        # early on an unchanged permission set, which would skip the check.
        narrowed = await service.update_role(
            ws["id"],
            role_ids["editor"],
            permissions=["member:read", "audit:read"],
            actor=admin_user,
        )
        assert sorted(narrowed.permissions) == ["audit:read", "member:read"]

        member.status = "suspended"
        await session.commit()

        with pytest.raises(WorkspaceForbidden):
            await service.create_custom_role(
                ws["id"],
                name="ops",
                description=None,
                permissions=["member:read"],
                actor=admin_user,
            )
        with pytest.raises(WorkspaceForbidden):
            await service.update_role(
                ws["id"], role_ids["editor"], permissions=["member:read"], actor=admin_user
            )
        # #1126: the name branch resolved no membership at all, so a
        # suspended caller renamed `editor` — which also flips `system` and opts
        # the seeded role out of boot-time convergence.
        with pytest.raises(WorkspaceForbidden):
            await service.update_role(
                ws["id"], role_ids["editor"], name="suspended-rename", actor=admin_user
            )
        # Same hole in the sibling writer: an empty permission list cannot trip
        # the permission check, so it was the only path that mutated with no cap.
        with pytest.raises(WorkspaceForbidden):
            await service.create_custom_role(
                ws["id"],
                name="ops-empty",
                description=None,
                permissions=[],
                actor=admin_user,
            )
        # Re-read via a fresh session so the assertions are on the stored rows.
        async with SessionFactory() as check:
            stored = await check.get(Role, role_ids["editor"])
            assert stored is not None
            assert stored.name == "editor"
            leftovers = await check.scalars(
                select(Role).where(Role.workspace_id == ws["id"], Role.name == "ops-empty")
            )
            assert leftovers.first() is None


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


async def test_legacy_owner_case_row_is_not_editable(app_client):
    """`Owner` is refused the same 403 the seeded `owner` row gets (#593).

    The row is the owner role written with the wrong case, so it inherits the
    owner guard rather than the custom-role edit path.
    """
    client = app_client
    owner = await register_user(client, "ci8@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    role_id = await _seed_legacy_case_role(ws["id"])

    desc = await client.patch(
        f"/api/v1/roles/{role_id}", json={"description": "renamed"}, headers=headers
    )
    assert desc.status_code == 403, desc.text

    rename = await client.patch(
        f"/api/v1/roles/{role_id}", json={"name": "superuser"}, headers=headers
    )
    assert rename.status_code == 403, rename.text


async def test_legacy_owner_case_row_cannot_be_assigned(app_client):
    """Assigning the legacy row is the same 409 the seeded `owner` row gets."""
    client = app_client
    owner = await register_user(client, "ci9@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    role_id = await _seed_legacy_case_role(ws["id"])
    await _add_member(client, owner, ws, "ci9t@example.com", "editor")
    target_id = await _membership_id(client, owner, ws, "ci9t@example.com")

    assign = await client.patch(
        f"/api/v1/members/{target_id}", json={"role_id": role_id}, headers=headers
    )
    assert assign.status_code == 409, assign.text

    # Same guard on the member who already holds it: the owner role cannot be edited.
    _holder, held = await _add_member_holding_role(client, owner, ws, "ci9h@example.com", role_id)
    reassign = await client.patch(
        f"/api/v1/members/{held}",
        json={"role_id": await _role_id(client, headers, "editor")},
        headers=headers,
    )
    assert reassign.status_code == 409, reassign.text


async def test_legacy_owner_case_row_cannot_be_removed_suspended_or_left(app_client):
    """remove_member, suspend_member and leave_workspace all refuse the owner role."""
    client = app_client
    owner = await register_user(client, "ci10@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    role_id = await _seed_legacy_case_role(ws["id"])
    _holder, membership_id = await _add_member_holding_role(
        client, owner, ws, "ci10r@example.com", role_id
    )

    removed = await client.delete(f"/api/v1/members/{membership_id}", headers=headers)
    assert removed.status_code == 409, removed.text

    suspended = await client.post(f"/api/v1/members/{membership_id}/suspend", headers=headers)
    assert suspended.status_code == 409, suspended.text

    leaver, _ = await _add_member_holding_role(client, owner, ws, "ci10l@example.com", role_id)
    left = await client.delete(
        f"/api/v1/workspaces/{ws['id']}/membership",
        headers=auth_headers(leaver),
    )
    assert left.status_code == 409, left.text


async def test_legacy_owner_case_row_cannot_be_invited_to(app_client):
    """Inviting to the legacy owner row is the same 409 as the seeded row."""
    client = app_client
    owner = await register_user(client, "ci11@example.com")
    ws = await create_workspace(client, owner)
    role_id = await _seed_legacy_case_role(ws["id"])

    resp = await client.post(
        "/api/v1/invitations",
        json={"email": "ci11i@example.com", "role_id": role_id},
        headers=ws_headers(owner, ws["id"]),
    )
    assert resp.status_code == 409, resp.text


async def test_legacy_owner_case_row_counts_as_owner_for_transfer_and_manager_gates(
    app_client,
):
    """The actor-gate half: a member holding the legacy row is an owner, not a custom role.

    The row carries `*` because that is what a role meant to be the owner holds;
    the route guards are permission-based and admit it either way, so what these
    calls exercise is the name-based gate in the service.
    """
    client = app_client
    owner = await register_user(client, "ci12@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    role_id = await _seed_legacy_case_role(ws["id"], permissions=["*"])
    heir, _ = await _add_member_holding_role(client, owner, ws, "ci12h@example.com", role_id)
    heir_headers = ws_headers(heir, ws["id"])

    # set_member_role's actor gate: admits owner-or-admin.
    editor_id = await _role_id(client, headers, "editor")
    await _add_member(client, owner, ws, "ci12t@example.com", "viewer")
    promoted = await client.patch(
        f"/api/v1/members/{await _membership_id(client, owner, ws, 'ci12t@example.com')}",
        json={"role_id": editor_id},
        headers=heir_headers,
    )
    assert promoted.status_code == 200, promoted.text

    # _require_manager: admits owner-or-admin, and remove_member only refuses the owner role.
    await _add_member(client, owner, ws, "ci12r@example.com", "viewer")
    removed = await client.delete(
        f"/api/v1/members/{await _membership_id(client, owner, ws, 'ci12r@example.com')}",
        headers=heir_headers,
    )
    assert removed.status_code == 204, removed.text

    # transfer_ownership: only the owner may transfer.
    await _add_member(client, owner, ws, "ci12s@example.com", "editor")
    target_id = await _membership_id(client, owner, ws, "ci12s@example.com")
    transfer = await client.post(
        f"/api/v1/workspaces/{ws['id']}/transfer",
        json={"new_owner_membership_id": target_id},
        headers=heir_headers,
    )
    assert transfer.status_code == 200, transfer.text
    roles = {
        m["email"]: m["role"] for m in (await client.get("/api/v1/members", headers=headers)).json()
    }
    assert roles["ci12s@example.com"] == "owner"
    assert roles["ci12h@example.com"] == "admin"


async def test_legacy_admin_case_row_counts_as_admin_at_the_manager_gates(app_client):
    """The `admin` half of the manager gate is case-insensitive, and name-only.

    #624 replaced an exact `("owner", "admin")` comparison with
    `is_manager_role_name`, so a pre-#328 `Admin` row beside the seeded `admin`
    is admitted at both gates where it used to be refused. The row carries the
    admin role's own permission set and no `"*"`: `"*"` is reserved for the
    owner role, so an `Admin` row an admin created never had it. That set holds
    the `member:update` / `member:delete` the route guards require, so these
    calls exercise the name-only service gate rather than a permission.
    """
    client = app_client
    owner = await register_user(client, "ci15@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    role_id = await _seed_legacy_case_role(
        ws["id"], "Admin", permissions=perms.permissions_for_role("admin")
    )
    holder, _ = await _add_member_holding_role(client, owner, ws, "ci15h@example.com", role_id)
    holder_headers = ws_headers(holder, ws["id"])

    # set_member_role's actor gate: admits owner-or-admin.
    editor_id = await _role_id(client, headers, "editor")
    await _add_member(client, owner, ws, "ci15t@example.com", "viewer")
    promoted = await client.patch(
        f"/api/v1/members/{await _membership_id(client, owner, ws, 'ci15t@example.com')}",
        json={"role_id": editor_id},
        headers=holder_headers,
    )
    assert promoted.status_code == 200, promoted.text

    # _require_manager, through remove_member: only the owner role is refused.
    await _add_member(client, owner, ws, "ci15r@example.com", "viewer")
    removed = await client.delete(
        f"/api/v1/members/{await _membership_id(client, owner, ws, 'ci15r@example.com')}",
        headers=holder_headers,
    )
    assert removed.status_code == 204, removed.text

    # The holder is on the legacy row itself, not on the seeded `admin`.
    roles = {
        m["email"]: m["role"] for m in (await client.get("/api/v1/members", headers=headers)).json()
    }
    assert roles["ci15h@example.com"] == "Admin"
    assert roles["ci15t@example.com"] == "editor"


async def test_legacy_owner_case_row_transfers_without_the_owner_permission(app_client):
    """`transfer_ownership` gates on the name alone, whatever the row carries.

    `*` is reserved for the owner role, so a legacy `Owner` row an admin
    created pre-#328 carries none — the realistic shape. The service gate reads
    the name only, so such a holder still transfers ownership away from the
    seeded owner. Pinned as the current contract, per the review on #624.
    """
    client = app_client
    owner = await register_user(client, "ci14@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    role_id = await _seed_legacy_case_role(ws["id"])
    heir, _ = await _add_member_holding_role(client, owner, ws, "ci14h@example.com", role_id)
    heir_headers = ws_headers(heir, ws["id"])
    await _add_member(client, owner, ws, "ci14t@example.com", "editor")
    target_id = await _membership_id(client, owner, ws, "ci14t@example.com")

    transfer = await client.post(
        f"/api/v1/workspaces/{ws['id']}/transfer",
        json={"new_owner_membership_id": target_id},
        headers=heir_headers,
    )
    assert transfer.status_code == 200, transfer.text
    roles = {
        m["email"]: m["role"] for m in (await client.get("/api/v1/members", headers=headers)).json()
    }
    assert roles["ci14t@example.com"] == "owner"
    assert roles["ci14h@example.com"] == "admin"


async def test_transfer_finds_the_owner_and_admin_rows_by_case_folded_name(app_client):
    """The gate and the lookup have to fold alike.

    `transfer_ownership` gates on `is_owner_role_name` and then resolves both
    roles it writes through `_role_by_name`, which compared `Role.name` exactly:
    a workspace whose owner row is spelled `Owner` passed the gate and 404'd on
    the lookup, which is what the client fix in #772 exposed.
    """
    client = app_client
    owner = await register_user(client, "ci16@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    await _rename_seeded_role(ws["id"], "owner", "Owner")
    await _rename_seeded_role(ws["id"], "admin", "Admin")
    await _add_member(client, owner, ws, "ci16h@example.com", "editor")
    target_id = await _membership_id(client, owner, ws, "ci16h@example.com")

    transfer = await client.post(
        f"/api/v1/workspaces/{ws['id']}/transfer",
        json={"new_owner_membership_id": target_id},
        headers=headers,
    )
    assert transfer.status_code == 200, transfer.text
    roles = {
        m["email"]: m["role"] for m in (await client.get("/api/v1/members", headers=headers)).json()
    }
    assert roles["ci16h@example.com"] == "Owner"
    assert roles["ci16@example.com"] == "Admin"


async def test_check_name_free_names_the_seeded_row(app_client):
    """The 409 names the system row, not whichever row `.first()` returns (#592).

    A workspace created before the case-insensitive check can hold `admin` +
    `Admin`; the two rows are indistinguishable to the predicate, so the order
    has to be total for the message to be deterministic. The seeded `admin` is
    deleted and re-added after `Admin`, so storage order disagrees with the
    intended one and an unordered `.first()` names `Admin`.
    """
    from sqlalchemy import select

    from src.db.session import SessionFactory
    from src.models.workspace import Role

    client = app_client
    owner = await register_user(client, "ci13@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    async with SessionFactory() as session:
        seeded = await session.execute(
            select(Role).where(Role.workspace_id == ws["id"], Role.name == "admin")
        )
        admin = seeded.scalar_one()
        admin_fields = {"description": admin.description, "permissions": list(admin.permissions)}
        await session.delete(admin)
        await session.commit()
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
        session.add(Role(workspace_id=ws["id"], name="admin", system=True, **admin_fields))
        await session.commit()

    created = await client.post(
        "/api/v1/roles", json={"name": "ops", "permissions": []}, headers=headers
    )
    assert created.status_code == 201, created.text

    resp = await client.post(
        "/api/v1/roles", json={"name": "ADMIN", "permissions": []}, headers=headers
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "a role named 'admin' already exists"

    renamed = await client.patch(
        f"/api/v1/roles/{created.json()['id']}", json={"name": "admin"}, headers=headers
    )
    assert renamed.status_code == 409, renamed.text
    assert renamed.json()["detail"] == "a role named 'admin' already exists"


async def test_folded_role_lookups_resolve_the_same_row(app_client):
    """The two folded lookups must not disagree about an indistinguishable pair.

    `_check_name_free` and `_role_by_name` fold the same predicate, so a pair
    they cannot tell apart has to resolve to the same row at both: the 409 that
    names the row and the row `transfer_ownership` hands out. `_role_by_name`
    ranked `Role.name != name`, so it picked the exact-case custom `admin` while
    the 409 named the seeded `Admin` — the pair a pre-#328 workspace holds when
    its seeded row was renamed to a case variant and a custom role then took the
    exact name, both of which the name check allowed then.
    """
    client = app_client
    owner = await register_user(client, "ci17@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    await _rename_seeded_role(ws["id"], "admin", "Admin")
    await _seed_legacy_case_role(ws["id"], "admin")
    heir = await _add_member(client, owner, ws, "ci17h@example.com", "editor")
    target_id = await _membership_id(client, owner, ws, "ci17h@example.com")

    created = await client.post(
        "/api/v1/roles", json={"name": "ops", "permissions": []}, headers=headers
    )
    assert created.status_code == 201, created.text
    conflict = await client.post(
        "/api/v1/roles", json={"name": "admin", "permissions": []}, headers=headers
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"] == "a role named 'Admin' already exists"

    transfer = await client.post(
        f"/api/v1/workspaces/{ws['id']}/transfer",
        json={"new_owner_membership_id": target_id},
        headers=headers,
    )
    assert transfer.status_code == 200, transfer.text
    # Read with the new owner's headers: the demoted owner's row is what the
    # lookup picked, so they may not be able to list anything.
    members = await client.get("/api/v1/members", headers=ws_headers(heir, ws["id"]))
    assert members.status_code == 200, members.text
    roles = {m["email"]: m["role"] for m in members.json()}
    assert roles["ci17@example.com"] == "Admin"
