from tests.conftest import app_client, auth_headers, create_workspace, register_user, ws_headers


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


async def test_workspace_settings_crud_and_validation(app_client):
    client = app_client
    owner = await register_user(client, "ws-owner@example.com")
    ws = await create_workspace(client, owner)
    hdr = ws_headers(owner, ws["id"])

    # unknown key → 422
    resp = await client.put("/api/v1/workspace-settings/not.a.key", json={"value": "x"}, headers=hdr)
    assert resp.status_code == 422

    # enum bad value → 422
    resp = await client.put("/api/v1/workspace-settings/agents.default_runner", json={"value": "docker"}, headers=hdr)
    assert resp.status_code == 422

    # bad type (bool expected) → 422
    resp = await client.put("/api/v1/workspace-settings/agents.memory_enabled", json={"value": "yes"}, headers=hdr)
    assert resp.status_code == 422

    # valid put
    resp = await client.put("/api/v1/workspace-settings/agents.default_runner", json={"value": "vercel"}, headers=hdr)
    assert resp.status_code == 200, resp.text
    assert resp.json()["key"] == "agents.default_runner"
    assert resp.json()["value"] == "vercel"

    # GET single
    resp = await client.get("/api/v1/workspace-settings/agents.default_runner", headers=hdr)
    assert resp.status_code == 200
    assert resp.json()["value"] == "vercel"

    # list contains it
    resp = await client.get("/api/v1/workspace-settings", headers=hdr)
    assert resp.status_code == 200
    keys = [r["key"] for r in resp.json()]
    assert "agents.default_runner" in keys

    # sensitive token masked
    resp = await client.put("/api/v1/workspace-settings/agents.sandbox.vercel_token", json={"value": "s3cr3t"}, headers=hdr)
    assert resp.status_code == 200
    assert resp.json()["value"] == {"has_value": True}
    resp = await client.get("/api/v1/workspace-settings", headers=hdr)
    token_entry = next((r for r in resp.json() if r["key"] == "agents.sandbox.vercel_token"), None)
    assert token_entry is not None
    assert token_entry["value"] == {"has_value": True}
    assert "s3cr3t" not in str(resp.json())

    # delete token → 404 for GET
    resp = await client.delete("/api/v1/workspace-settings/agents.sandbox.vercel_token", headers=hdr)
    assert resp.status_code == 204
    resp = await client.get("/api/v1/workspace-settings/agents.sandbox.vercel_token", headers=hdr)
    assert resp.status_code == 404

    # delete non-existent → 404
    resp = await client.delete("/api/v1/workspace-settings/agents.sandbox.vercel_token", headers=hdr)
    assert resp.status_code == 404


async def test_workspace_settings_null_clears(app_client):
    client = app_client
    owner = await register_user(client, "ws-null2@example.com")
    ws = await create_workspace(client, owner)
    hdr = ws_headers(owner, ws["id"])
    # set then clear via null
    resp = await client.put("/api/v1/workspace-settings/agents.default_runner", json={"value": "local"}, headers=hdr)
    assert resp.status_code == 200
    resp = await client.put("/api/v1/workspace-settings/agents.default_runner", json={"value": None}, headers=hdr)
    assert resp.status_code == 200
    assert resp.json()["value"] is None
    resp = await client.get("/api/v1/workspace-settings/agents.default_runner", headers=hdr)
    assert resp.status_code == 404
    # list no longer contains it
    resp = await client.get("/api/v1/workspace-settings", headers=hdr)
    assert "agents.default_runner" not in [r["key"] for r in resp.json()]


async def test_workspace_settings_permission(app_client):
    client = app_client
    owner = await register_user(client, "ws-perm-owner@example.com")
    ws = await create_workspace(client, owner)
    hdr_owner = ws_headers(owner, ws["id"])
    invite = await _invite_as(client, owner, ws["id"], "ws-editor@example.com", "editor")
    ed = await register_user(client, "ws-editor@example.com")
    r = await client.post("/api/v1/invitations/accept", params={"token": invite["token"]}, headers=auth_headers(ed))
    assert r.status_code == 200, r.text
    ed_hdr = ws_headers(ed, ws["id"])
    # editor can GET
    resp = await client.get("/api/v1/workspace-settings", headers=ed_hdr)
    assert resp.status_code == 200
    # editor cannot PUT (needs workspace:update)
    resp = await client.put("/api/v1/workspace-settings/agents.default_runner", json={"value": "local"}, headers=ed_hdr)
    assert resp.status_code == 403
    # editor cannot DELETE
    # first owner creates one
    await client.put("/api/v1/workspace-settings/agents.default_runner", json={"value": "local"}, headers=hdr_owner)
    resp = await client.delete("/api/v1/workspace-settings/agents.default_runner", headers=ed_hdr)
    assert resp.status_code == 403


async def test_workspace_settings_cross_workspace_isolation(app_client):
    client = app_client
    owner = await register_user(client, "ws-iso@example.com")
    ws1 = await create_workspace(client, owner, name="Iso 1")
    ws2 = await create_workspace(client, owner, name="Iso 2")
    h1 = ws_headers(owner, ws1["id"])
    h2 = ws_headers(owner, ws2["id"])
    await client.put("/api/v1/workspace-settings/agents.default_runner", json={"value": "vercel"}, headers=h1)
    resp = await client.get("/api/v1/workspace-settings/agents.default_runner", headers=h2)
    assert resp.status_code == 404
    resp = await client.get("/api/v1/workspace-settings", headers=h2)
    assert "agents.default_runner" not in [r["key"] for r in resp.json()]
