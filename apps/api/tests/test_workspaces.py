import pytest
from sqlalchemy import select

from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


async def test_create_and_list_workspace(app_client):
    client = app_client
    tokens = await register_user(client, "dave@example.com")
    ws = await create_workspace(client, tokens, name="Globex")
    assert ws["slug"] == "globex"
    assert ws["role"] == "owner"

    listed = await client.get("/api/v1/workspaces", headers=auth_headers(tokens))
    assert listed.status_code == 200
    assert len(listed.json()) == 1


async def _invite(client, owner_tokens, ws, email: str, role_name: str) -> str:
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner_tokens, ws["id"]))
    role_id = next(r["id"] for r in roles.json() if r["name"] == role_name)
    created = await client.post(
        "/api/v1/invitations",
        json={"email": email, "role_id": role_id},
        headers=ws_headers(owner_tokens, ws["id"]),
    )
    assert created.status_code == 201, created.text
    return created.json()["token"]


async def test_onboarding_flag_defaults_on_and_toggles(app_client):
    client = app_client
    tokens = await register_user(client, "onb1@example.com")
    ws = await create_workspace(client, tokens)

    # Default-on: an absent flag means the card is shown.
    assert ws["onboarding_enabled"] is True

    off = await client.patch(
        f"/api/v1/workspaces/{ws['id']}",
        json={"onboarding_enabled": False},
        headers=ws_headers(tokens, ws["id"]),
    )
    assert off.status_code == 200
    assert off.json()["onboarding_enabled"] is False

    reread = await client.get(
        f"/api/v1/workspaces/{ws['id']}", headers=ws_headers(tokens, ws["id"])
    )
    assert reread.json()["onboarding_enabled"] is False

    # Re-enabling drops the stored False instead of leaving a no-op key.
    on = await client.patch(
        f"/api/v1/workspaces/{ws['id']}",
        json={"onboarding_enabled": True},
        headers=ws_headers(tokens, ws["id"]),
    )
    assert on.json()["onboarding_enabled"] is True


async def test_onboarding_flag_omitted_leaves_flag_untouched(app_client):
    client = app_client
    tokens = await register_user(client, "onb2@example.com")
    ws = await create_workspace(client, tokens)
    await client.patch(
        f"/api/v1/workspaces/{ws['id']}",
        json={"onboarding_enabled": False},
        headers=ws_headers(tokens, ws["id"]),
    )

    # A name-only patch must not silently re-enable onboarding.
    resp = await client.patch(
        f"/api/v1/workspaces/{ws['id']}",
        json={"name": "Renamed"},
        headers=ws_headers(tokens, ws["id"]),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    assert resp.json()["onboarding_enabled"] is False


async def test_onboarding_flag_rejects_non_bool(app_client):
    client = app_client
    tokens = await register_user(client, "onb3@example.com")
    ws = await create_workspace(client, tokens)

    for bad in ("false", 0, 1, "no"):
        resp = await client.patch(
            f"/api/v1/workspaces/{ws['id']}",
            json={"onboarding_enabled": bad},
            headers=ws_headers(tokens, ws["id"]),
        )
        assert resp.status_code == 422, bad


async def test_onboarding_flag_gated_on_workspace_update(app_client):
    client = app_client
    owner = await register_user(client, "onb4@example.com")
    ws = await create_workspace(client, owner)

    # An admin holds workspace:update, so the toggle is allowed for them too.
    admin = await register_user(client, "onb5@example.com")
    token = await _invite(client, owner, ws, "onb5@example.com", "admin")
    accepted = await client.post(
        f"/api/v1/invitations/accept?token={token}", headers=auth_headers(admin)
    )
    assert accepted.status_code == 200, accepted.text
    allowed = await client.patch(
        f"/api/v1/workspaces/{ws['id']}",
        json={"onboarding_enabled": False},
        headers=ws_headers(admin, ws["id"]),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["onboarding_enabled"] is False

    # A viewer has no workspace:update and must be refused.
    viewer = await register_user(client, "onb6@example.com")
    vtoken = await _invite(client, owner, ws, "onb6@example.com", "viewer")
    await client.post(f"/api/v1/invitations/accept?token={vtoken}", headers=auth_headers(viewer))
    denied = await client.patch(
        f"/api/v1/workspaces/{ws['id']}",
        json={"onboarding_enabled": True},
        headers=ws_headers(viewer, ws["id"]),
    )
    assert denied.status_code == 403


async def test_workspace_roles_seeded(app_client):
    client = app_client
    tokens = await register_user(client, "erin@example.com")
    ws = await create_workspace(client, tokens)

    roles = await client.get("/api/v1/roles", headers=ws_headers(tokens, ws["id"]))
    assert roles.status_code == 200
    names = {r["name"] for r in roles.json()}
    assert names == {"owner", "admin", "editor", "viewer"}


async def test_non_member_blocked(app_client):
    client = app_client
    tokens = await register_user(client, "frank@example.com")
    ws = await create_workspace(client, tokens)

    other = await register_user(client, "grace@example.com")
    resp = await client.get("/api/v1/workspaces/" + ws["id"], headers=ws_headers(other, ws["id"]))
    assert resp.status_code == 403


async def test_permission_denied_without_privilege(app_client):
    client = app_client
    tokens = await register_user(client, "henry@example.com")
    ws = await create_workspace(client, tokens)

    # viewer member cannot create workspaces (no workspace:create permission)
    other = await register_user(client, "iris@example.com")
    roles = await client.get("/api/v1/roles", headers=ws_headers(tokens, ws["id"]))
    viewer = next(r for r in roles.json() if r["name"] == "viewer")
    invite = await client.post(
        "/api/v1/invitations",
        json={"email": "iris@example.com", "role_id": viewer["id"]},
        headers=ws_headers(tokens, ws["id"]),
    )
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite.json()["token"]},
        headers=auth_headers(other),
    )

    # Try to manage members as viewer (missing member:update permission)
    resp = await client.get(
        "/api/v1/members",
        headers=ws_headers(other, ws["id"]),
    )
    # members:list is allowed for all members, so check 200
    assert resp.status_code == 200

    # Try to manage roles as viewer (missing role:create permission)
    resp = await client.post(
        "/api/v1/roles",
        json={"name": "custom", "permissions": ["workspace:read"]},
        headers=ws_headers(other, ws["id"]),
    )
    assert resp.status_code == 403
    assert "missing permission" in resp.json()["detail"]


async def test_refine_compliant_list_query(app_client):
    client = app_client
    tokens = await register_user(client, "jane@example.com")
    for i in range(5):
        await create_workspace(client, tokens, name=f"WS {i}")

    resp = await client.get(
        "/api/v1/workspaces?offset=0&limit=2&sort[]=name&order[]=asc",
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "5"
    body = resp.json()
    assert len(body) == 2
    assert body[0]["name"] == "WS 0"

    ids = [w["id"] for w in body]
    resp = await client.get(
        "/api/v1/workspaces?" + "&".join(f"ids[]={i}" for i in ids),
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_simple_rest_range_pagination_query(app_client):
    """simple-rest's default server pagination (`_start`/`_end`) and comma-
    joined `_sort`/`_order`, plus its `id=` getMany format, must all parse."""
    client = app_client
    tokens = await register_user(client, "jared@example.com")
    for i in range(5):
        await create_workspace(client, tokens, name=f"WS {i}")

    resp = await client.get(
        "/api/v1/workspaces?_start=0&_end=2&_sort=name&_order=asc",
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "5"
    body = resp.json()
    assert len(body) == 2
    assert body[0]["name"] == "WS 0"

    # page 2
    resp = await client.get(
        "/api/v1/workspaces?_start=2&_end=4&_sort=name&_order=asc",
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 200
    assert [w["name"] for w in resp.json()] == ["WS 2", "WS 3"]

    # desc order
    resp = await client.get(
        "/api/v1/workspaces?_start=0&_end=2&_sort=name&_order=desc",
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "WS 4"

    # getMany format: repeated `id=` params
    ids = [w["id"] for w in body]
    resp = await client.get(
        "/api/v1/workspaces?" + "&".join(f"id={i}" for i in ids),
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_suspended_actor_cannot_widen_a_custom_role(app_client):
    """A suspended actor is capped as if unauthenticated, not by its own role.

    The role-capping sites resolve the actor's membership with
    `active_only=True`; a suspended row therefore reads as "no actor cap" and
    every requested permission is denied.
    """
    from src.db.session import SessionFactory
    from src.models.workspace import Role, WorkspaceMember
    from src.services.auth import AuthService
    from src.services.workspaces import WorkspaceForbidden, WorkspaceService

    client = app_client
    owner = await register_user(client, "cap-owner@example.com")
    ws = await create_workspace(client, owner)
    await register_user(client, "cap-admin@example.com")

    async with SessionFactory() as session:
        service = WorkspaceService(session)
        admin_user = await AuthService(session).get_by_email("cap-admin@example.com")
        role_ids = {
            name: (
                await session.execute(
                    select(Role).where(Role.workspace_id == ws["id"], Role.name == name)
                )
            )
            .scalar_one()
            .id
            for name in ("admin", "editor")
        }
        session.add(
            WorkspaceMember(
                workspace_id=ws["id"],
                user_id=admin_user.id,
                role_id=role_ids["admin"],
                status="suspended",
            )
        )
        await session.commit()

        # `member:read` is in the admin role's permission set, so this only
        # fails when the suspended membership is not treated as an actor cap.
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


async def test_service_stores_trimmed_names(app_client):
    """The service trims even when no schema validated the input.

    The schema is the validation boundary; the service is the normalization
    boundary. Direct callers (seed, bootstrap, tests) never pass through the
    schema, so a padded name must not reach the row.
    """
    from src.db.session import SessionFactory
    from src.models.workspace import Role, Workspace
    from src.services.auth import AuthService
    from src.services.workspaces import WorkspaceService

    client = app_client
    await register_user(client, "trim-owner@example.com")

    async with SessionFactory() as session:
        service = WorkspaceService(session)
        user = await AuthService(session).get_by_email("trim-owner@example.com")
        workspace = await service.create_workspace(
            name="  Acme  ", slug=None, description=None, owner=user
        )
        role = await service.create_custom_role(
            workspace.id,
            name="  ops  ",
            description=None,
            permissions=["member:read"],
            actor=user,
        )
        await service.update_workspace(workspace.id, name="  Acme Renamed  ")
        await service.update_role(workspace.id, role.id, name="  operators  ")

    # Re-read so the assertion is on the stored row, not the in-memory object.
    async with SessionFactory() as session:
        stored_ws = await session.get(Workspace, workspace.id)
        assert stored_ws.name == "Acme Renamed"
        assert stored_ws.slug == "acme"
        stored_role = await session.get(Role, role.id)
        assert stored_role.name == "operators"


async def test_create_workspace_strips_padded_name(app_client):
    client = app_client
    tokens = await register_user(client, "pad-ws@example.com")
    resp = await client.post(
        "/api/v1/workspaces", json={"name": "  Acme  "}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "Acme"
    assert resp.json()["slug"] == "acme"

    blank = await client.post(
        "/api/v1/workspaces", json={"name": "   "}, headers=auth_headers(tokens)
    )
    assert blank.status_code == 422


async def test_update_workspace_strips_padded_name(app_client):
    client = app_client
    tokens = await register_user(client, "pad-ws-upd@example.com")
    ws = await create_workspace(client, tokens, name="Acme Corp")
    headers = ws_headers(tokens, ws["id"])
    resp = await client.patch(
        f"/api/v1/workspaces/{ws['id']}", json={"name": "  Acme Renamed  "}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Acme Renamed"

    blank = await client.patch(
        f"/api/v1/workspaces/{ws['id']}", json={"name": "   "}, headers=headers
    )
    assert blank.status_code == 422


async def _set_member_status(membership_id: str, status: str) -> None:
    from src.db.session import SessionFactory
    from src.models.workspace import WorkspaceMember

    async with SessionFactory() as session:
        member = await session.get(WorkspaceMember, membership_id)
        assert member is not None
        member.status = status
        await session.commit()


async def test_transfer_ownership_refuses_every_non_active_status(app_client):
    """Both terminal statuses are refused and `active` is still offered.

    `transfer_ownership` decides from a table over the member-status domain
    (#810), so both halves are pinned: an assertion on the refusal side alone
    also passes against a `!= "active"` comparison, and one on the offer side
    alone misses a table that grants every status.
    """
    client = app_client
    owner = await register_user(client, "xfer-owner@example.com")
    ws = await create_workspace(client, owner)
    heir = await register_user(client, "xfer-heir@example.com")
    token = await _invite(client, owner, ws, "xfer-heir@example.com", "editor")
    accepted = await client.post(
        f"/api/v1/invitations/accept?token={token}", headers=auth_headers(heir)
    )
    assert accepted.status_code == 200, accepted.text
    members = await client.get("/api/v1/members", headers=ws_headers(owner, ws["id"]))
    target_id = next(
        m["membership_id"] for m in members.json() if m["email"] == "xfer-heir@example.com"
    )
    headers = ws_headers(owner, ws["id"])

    for status in ("suspended", "invited"):
        await _set_member_status(target_id, status)
        refused = await client.post(
            f"/api/v1/workspaces/{ws['id']}/transfer",
            json={"new_owner_membership_id": target_id},
            headers=headers,
        )
        assert refused.status_code == 409, status
        assert refused.json()["detail"] == "new owner must be an active member"

    await _set_member_status(target_id, "active")
    transferred = await client.post(
        f"/api/v1/workspaces/{ws['id']}/transfer",
        json={"new_owner_membership_id": target_id},
        headers=headers,
    )
    assert transferred.status_code == 200, transferred.text
    roles = await client.get("/api/v1/members", headers=headers)
    heir_row = next(m for m in roles.json() if m["email"] == "xfer-heir@example.com")
    assert heir_row["role"] == "owner"


def test_transfer_eligibility_decides_every_member_status():
    """A status the domain gains is refused until this table decides it."""
    from src.models.workspace import MemberStatus
    from src.services.workspaces import _TRANSFER_ELIGIBLE

    assert set(_TRANSFER_ELIGIBLE) == {status.value for status in MemberStatus}
