from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


async def _invite_as(app_client, owner, workspace_id, email, role_name="editor"):
    roles = await app_client.get("/api/v1/roles", headers=ws_headers(owner, workspace_id))
    role_id = next(r["id"] for r in roles.json() if r["name"] == role_name)
    resp = await app_client.post(
        "/api/v1/invitations",
        json={"email": email, "role_id": role_id},
        headers=ws_headers(owner, workspace_id),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_owner_can_create_list_get_patch_delete_agent(app_client):
    client = app_client
    owner = await register_user(client, "ag-owner@example.com")
    ws = await create_workspace(client, owner)
    hdr = ws_headers(owner, ws["id"])

    # create minimal -> slug auto-generated
    r = await client.post("/api/v1/agents", json={"name": "Helper Bot"}, headers=hdr)
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["slug"] == "helper-bot"
    assert a["is_active"] is True
    assert a["mcp_servers"] == []
    assert a["skills"] == []
    aid = a["id"]

    # list with X-Total-Count
    r = await client.get("/api/v1/agents", headers=hdr)
    assert r.status_code == 200
    assert r.headers.get("X-Total-Count") == "1"
    assert len(r.json()) == 1

    # get
    r = await client.get(f"/api/v1/agents/{aid}", headers=hdr)
    assert r.status_code == 200
    assert r.json()["id"] == aid

    # patch
    r = await client.patch(f"/api/v1/agents/{aid}", json={"description": "helpful"}, headers=hdr)
    assert r.status_code == 200
    assert r.json()["description"] == "helpful"

    # delete
    r = await client.delete(f"/api/v1/agents/{aid}", headers=hdr)
    assert r.status_code == 204

    r = await client.get(f"/api/v1/agents/{aid}", headers=hdr)
    assert r.status_code == 404


async def test_slug_conflict_same_workspace_409_other_workspace_ok(app_client):
    client = app_client
    owner = await register_user(client, "ag-slug@example.com")
    ws1 = await create_workspace(client, owner, name="Ws One")
    ws2 = await create_workspace(client, owner, name="Ws Two")
    h1 = ws_headers(owner, ws1["id"])
    h2 = ws_headers(owner, ws2["id"])

    r = await client.post("/api/v1/agents", json={"name": "My Agent", "slug": "my-agent"}, headers=h1)
    assert r.status_code == 201

    r = await client.post("/api/v1/agents", json={"name": "My Agent", "slug": "my-agent"}, headers=h1)
    assert r.status_code == 409

    r = await client.post("/api/v1/agents", json={"name": "My Agent", "slug": "my-agent"}, headers=h2)
    assert r.status_code == 201
    assert r.json()["slug"] == "my-agent"


async def test_cross_workspace_access_is_404(app_client):
    client = app_client
    owner = await register_user(client, "ag-xws@example.com")
    ws1 = await create_workspace(client, owner, name="Ws A")
    ws2 = await create_workspace(client, owner, name="Ws B")
    h1 = ws_headers(owner, ws1["id"])
    h2 = ws_headers(owner, ws2["id"])
    r = await client.post("/api/v1/agents", json={"name": "Secret"}, headers=h1)
    aid = r.json()["id"]
    r = await client.get(f"/api/v1/agents/{aid}", headers=h2)
    assert r.status_code == 404


async def test_secret_key_validation_and_listing(app_client):
    client = app_client
    owner = await register_user(client, "ag-sec@example.com")
    ws = await create_workspace(client, owner)
    hdr = ws_headers(owner, ws["id"])
    r = await client.post("/api/v1/agents", json={"name": "Sec Bot"}, headers=hdr)
    aid = r.json()["id"]

    r = await client.put(f"/api/v1/agents/{aid}/secrets/bad-key", json={"value": "x"}, headers=hdr)
    assert r.status_code == 422

    r = await client.put(f"/api/v1/agents/{aid}/secrets/lowercase", json={"value": "x"}, headers=hdr)
    assert r.status_code == 422

    r = await client.put(f"/api/v1/agents/{aid}/secrets/VALID_KEY", json={"value": "s3cr3t"}, headers=hdr)
    assert r.status_code == 204

    r = await client.get(f"/api/v1/agents/{aid}/secrets", headers=hdr)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["key"] == "VALID_KEY"
    assert "value" not in str(data)
    assert "s3cr3t" not in str(data)

    r = await client.delete(f"/api/v1/agents/{aid}/secrets/VALID_KEY", headers=hdr)
    assert r.status_code == 204
    r = await client.get(f"/api/v1/agents/{aid}/secrets", headers=hdr)
    assert r.json() == []


async def test_foreign_role_is_422(app_client):
    client = app_client
    owner = await register_user(client, "ag-role@example.com")
    ws1 = await create_workspace(client, owner, name="Ws R1")
    ws2 = await create_workspace(client, owner, name="Ws R2")
    h1 = ws_headers(owner, ws1["id"])
    h2 = ws_headers(owner, ws2["id"])
    roles = await client.get("/api/v1/roles", headers=h2)
    foreign_role = roles.json()[0]["id"]
    r = await client.post("/api/v1/agents", json={"name": "Bad", "role_id": foreign_role}, headers=h1)
    assert r.status_code == 422


async def test_editor_can_read_but_not_manage(app_client):
    client = app_client
    owner = await register_user(client, "ag-perm-owner@example.com")
    ws = await create_workspace(client, owner)
    hdr = ws_headers(owner, ws["id"])
    invite = await _invite_as(client, owner, ws["id"], "ag-ed@example.com", "editor")
    ed = await register_user(client, "ag-ed@example.com")
    r = await client.post("/api/v1/invitations/accept", params={"token": invite["token"]}, headers=auth_headers(ed))
    assert r.status_code == 200, r.text
    ed_hdr = ws_headers(ed, ws["id"])

    r = await client.get("/api/v1/agents", headers=ed_hdr)
    assert r.status_code == 200

    r = await client.post("/api/v1/agents", json={"name": "Nope"}, headers=ed_hdr)
    assert r.status_code == 403
    assert "agent:manage" in r.json()["detail"]


async def test_viewer_can_read_but_not_manage(app_client):
    client = app_client
    owner = await register_user(client, "ag-viewer-owner@example.com")
    ws = await create_workspace(client, owner)
    invite = await _invite_as(client, owner, ws["id"], "ag-viewer@example.com", "viewer")
    viewer = await register_user(client, "ag-viewer@example.com")
    r = await client.post("/api/v1/invitations/accept", params={"token": invite["token"]}, headers=auth_headers(viewer))
    assert r.status_code == 200
    hdr = ws_headers(viewer, ws["id"])
    r = await client.get("/api/v1/agents", headers=hdr)
    assert r.status_code == 200
    r = await client.post("/api/v1/agents", json={"name": "Nope2"}, headers=hdr)
    assert r.status_code == 403


async def test_missing_workspace_header_400(app_client):
    client = app_client
    owner = await register_user(client, "ag-nohdr@example.com")
    await create_workspace(client, owner)
    r = await client.get("/api/v1/agents", headers=auth_headers(owner))
    assert r.status_code == 400


async def test_list_agents_bool_filter(app_client):
    """`is_active=true` (simple-rest flat filter) must not 500 — bool columns coerce."""
    client = app_client
    owner = await register_user(client, "bool-owner@example.com")
    ws = await create_workspace(client, owner)
    hdr = ws_headers(owner, ws["id"])

    r = await client.post("/api/v1/agents", json={"name": "Active One"}, headers=hdr)
    assert r.status_code == 201, r.text
    r = await client.post("/api/v1/agents", json={"name": "Sleepy", "is_active": False}, headers=hdr)
    assert r.status_code == 201, r.text

    r = await client.get("/api/v1/agents?is_active=true", headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1 and body[0]["name"] == "Active One"

    r = await client.get("/api/v1/agents?is_active=false", headers=hdr)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1 and r.json()[0]["name"] == "Sleepy"

    # invalid bool value → 422, not 500
    r = await client.get("/api/v1/agents?is_active=banana", headers=hdr)
    assert r.status_code == 422
