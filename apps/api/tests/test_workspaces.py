from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


async def test_create_and_list_workspace(app_client):
    client = app_client
    tokens = await register_user(client, "dave@example.com")
    ws = await create_workspace(client, tokens, name="Example Workspace")
    assert ws["slug"] == "example-workspace"
    assert ws["role"] == "owner"

    listed = await client.get("/api/v1/workspaces", headers=auth_headers(tokens))
    assert listed.status_code == 200
    assert len(listed.json()) == 1


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
