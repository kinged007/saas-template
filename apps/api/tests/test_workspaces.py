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


async def test_list_query_rejects_mismatched_sort_and_order_lengths(app_client):
    """More order[] than sort[] must be a client error, not an unhandled 500."""
    client = app_client
    tokens = await register_user(client, "kim@example.com")
    for query in (
        "sort[]=name&order[]=asc&order[]=desc",
        "_sort=name&_order=asc,desc",
    ):
        resp = await client.get(
            f"/api/v1/workspaces?{query}",
            headers=auth_headers(tokens),
        )
        assert resp.status_code == 422, resp.text
        assert "same number of entries" in resp.json()["detail"]


async def test_list_query_rejects_order_without_sort(app_client):
    """An order with no sort is malformed in either dialect (#968).

    `order[]=desc` alone reached the length guard while `_order=desc` alone
    parsed to an empty spec, so the same request was 422 or 200 depending on
    the parameter spelling. Both dialects are rejected.
    """
    client = app_client
    tokens = await register_user(client, "logan@example.com")
    for query in ("order[]=desc", "_order=desc"):
        resp = await client.get(
            f"/api/v1/workspaces?{query}",
            headers=auth_headers(tokens),
        )
        assert resp.status_code == 422, (query, resp.text)
        assert "same number of entries" in resp.json()["detail"]


async def test_list_query_rejects_unknown_sort_direction(app_client):
    """A direction that is neither asc nor desc must not read as ascending (#965).

    `apply_query` treats anything but `desc` as ascending, so a client with a
    typo in the direction got 200 and the wrong order with nothing to notice.
    Both dialects are refused, and the message names the values that are legal.
    """
    client = app_client
    tokens = await register_user(client, "monty@example.com")
    for i in range(3):
        await create_workspace(client, tokens, name=f"WS {i}")

    for query in (
        "_sort=name&_order=sideways",
        "_sort=name&_order=DESCENT",
        "_sort=name,created_at&_order=asc,sideways",
        "sort[]=name&order[]=sideways",
        "sort[]=name&sort[]=created_at&order[]=asc&order[]=sideways",
    ):
        resp = await client.get(
            f"/api/v1/workspaces?{query}",
            headers=auth_headers(tokens),
        )
        assert resp.status_code == 422, (query, resp.text)
        detail = resp.json()["detail"]
        assert "asc" in detail and "desc" in detail, detail


async def test_list_query_rejects_mixed_dialects(app_client):
    """One dialect per query, in both mixed spellings (#1054).

    `sort[]=name&_order=asc` reached the length guard with a message naming
    `sort[]`/`order[]`, the spelling the client never sent. Its mirror
    `_sort=name&order[]=desc` was worse: `order[]` was dropped, padded to
    `asc`, and answered 200 oldest-first. Both name the mix instead.
    """
    client = app_client
    tokens = await register_user(client, "nadia@example.com")
    for i in range(3):
        await create_workspace(client, tokens, name=f"WS {i}")

    for query in ("sort[]=name&_order=asc", "_sort=name&order[]=desc"):
        resp = await client.get(
            f"/api/v1/workspaces?{query}",
            headers=auth_headers(tokens),
        )
        assert resp.status_code == 422, (query, resp.text)
        detail = resp.json()["detail"]
        assert "_sort" in detail and "sort[]" in detail, detail


async def test_list_query_drops_empty_sort_fields_in_both_dialects(app_client):
    """An empty sort name means no sort in either dialect (#1056).

    `_sort=,` filtered the empty out and answered 200, while `?sort[]=` kept
    the empty and 422d on `sort on unknown field: `. Dropping an empty sort
    leaves a bare order, which is still an order with no sort (#968).
    """
    client = app_client
    tokens = await register_user(client, "oscar@example.com")
    for i in range(3):
        await create_workspace(client, tokens, name=f"WS {i}")

    for query in ("_sort=,", "sort[]="):
        resp = await client.get(
            f"/api/v1/workspaces?{query}",
            headers=auth_headers(tokens),
        )
        assert resp.status_code == 200, (query, resp.text)
        assert sorted(w["name"] for w in resp.json()) == ["WS 0", "WS 1", "WS 2"]

    # An empty order is no order: the surviving sort field keeps its default.
    for query in ("_sort=name,&_order=,", "sort[]=name&order[]="):
        resp = await client.get(
            f"/api/v1/workspaces?{query}",
            headers=auth_headers(tokens),
        )
        assert resp.status_code == 200, (query, resp.text)
        assert [w["name"] for w in resp.json()] == ["WS 0", "WS 1", "WS 2"]

    for query in ("_sort=,&_order=desc", "sort[]=&order[]=desc"):
        resp = await client.get(
            f"/api/v1/workspaces?{query}",
            headers=auth_headers(tokens),
        )
        assert resp.status_code == 422, (query, resp.text)
        assert "same number of entries" in resp.json()["detail"]


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


async def test_role_writers_require_an_actor(app_client):
    """A direct writer call names its actor: omission is not the system path.

    With an optional `actor`, leaving it off skipped the membership gate —
    that path could still flip a seeded role's `system` flag. The argument is
    required, so an omitted actor fails loudly instead of acting unbounded.
    """
    import pytest

    from src.db.session import SessionFactory
    from src.services.workspaces import WorkspaceService

    async with SessionFactory() as session:
        service = WorkspaceService(session)
        with pytest.raises(TypeError):
            await service.create_custom_role(
                "ws-x", name="ops", description=None, permissions=[]
            )
        with pytest.raises(TypeError):
            await service.update_role("ws-x", "role-x", name="ops")

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
        # The owner is an explicit actor: the writers have no opt-out-by-omission
        # system path, so a direct caller names who acts.
        await service.update_role(workspace.id, role.id, name="  operators  ", actor=user)

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


async def test_suspend_and_reactivate_agree_with_every_legal_status(app_client):
    """Both tables preserve today's behaviour for every status the CHECK allows.

    A suspend of an already-suspended member stays an idempotent 200 no-op, a
    reactivate of anything else stays a 409, a suspend of an `invited` member
    still succeeds, and a reactivate of a `suspended` member still succeeds.
    For every legal status the table and the comparison agree by design, so this
    is the behaviour-preservation pin; the fail-closed default is pinned at table
    level in `test_suspend_and_reactivate_decide_every_member_status`.
    """
    client = app_client
    owner = await register_user(client, "susp-owner@example.com")
    ws = await create_workspace(client, owner)
    token = await _invite(client, owner, ws, "susp-target@example.com", "editor")
    target = await register_user(client, "susp-target@example.com")
    accepted = await client.post(
        f"/api/v1/invitations/accept?token={token}", headers=auth_headers(target)
    )
    assert accepted.status_code == 200, accepted.text
    headers = ws_headers(owner, ws["id"])
    members = await client.get("/api/v1/members", headers=headers)
    target_id = next(
        m["membership_id"] for m in members.json() if m["email"] == "susp-target@example.com"
    )

    for status in ("active", "invited"):
        await _set_member_status(target_id, status)
        refused = await client.post(f"/api/v1/members/{target_id}/reactivate", headers=headers)
        assert refused.status_code == 409, status
        assert refused.json()["detail"] == "member is not suspended"

    await _set_member_status(target_id, "invited")
    suspended = await client.post(f"/api/v1/members/{target_id}/suspend", headers=headers)
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"

    again = await client.post(f"/api/v1/members/{target_id}/suspend", headers=headers)
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "suspended"

    # Pins the `SUSPENDED: True` row of `_REACTIVATE_ALLOWED`; the only other
    # successful reactivate lives in `test_workspace_lifecycle.py`, which does
    # not assert the status it wrote.
    reactivated = await client.post(f"/api/v1/members/{target_id}/reactivate", headers=headers)
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["status"] == "active"

    rows = await client.get("/api/v1/members", headers=headers)
    row = next(m for m in rows.json() if m["membership_id"] == target_id)
    assert row["status"] == "active"


def test_suspend_and_reactivate_decide_every_member_status():
    """A status the domain gains is refused by both tables until they decide it."""
    from src.models.workspace import MemberStatus
    from src.services.workspaces import _REACTIVATE_ALLOWED, _SUSPEND_ALLOWED

    every = {status.value for status in MemberStatus}
    assert set(_SUSPEND_ALLOWED) == every
    assert set(_REACTIVATE_ALLOWED) == every

    assert _SUSPEND_ALLOWED == {
        MemberStatus.ACTIVE.value: True,
        MemberStatus.INVITED.value: True,
        MemberStatus.SUSPENDED.value: False,
    }
    assert _REACTIVATE_ALLOWED == {
        MemberStatus.ACTIVE.value: False,
        MemberStatus.INVITED.value: False,
        MemberStatus.SUSPENDED.value: True,
    }

    # A status outside the CHECK domain fails closed in both directions: no
    # suspend write, no reactivate. `ck_workspace_members_status` is what makes
    # it unreachable through SQL, so the default is pinned here at table level.
    assert _SUSPEND_ALLOWED.get("archived", False) is False
    assert _REACTIVATE_ALLOWED.get("archived", False) is False
