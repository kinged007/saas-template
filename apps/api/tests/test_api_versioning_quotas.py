"""Issue #22: API versioning header + key usage counting/quotas."""

from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


async def test_api_version_header_on_api_responses(app_client):
    resp = await app_client.get("/")
    assert resp.status_code == 200
    assert resp.json()["api_version"] == "v1"

    owner = await register_user(app_client, "vera@example.com")
    await create_workspace(app_client, owner)
    resp = await app_client.get("/api/v1/workspaces", headers=auth_headers(owner))
    assert resp.headers.get("X-API-Version") == "v1"
    # non-API routes are not stamped
    assert "X-API-Version" not in (await app_client.get("/")).headers


async def test_key_usage_counted_and_visible(app_client):
    client = app_client
    owner = await register_user(client, "walt@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    created = (
        await client.post(
            "/api/v1/api-keys",
            json={"name": "metered", "permissions": ["member:read"]},
            headers=headers,
        )
    ).json()
    assert created["usage_count"] == 0
    assert created["usage_quota"] is None

    key_headers = {"Authorization": f"Bearer {created['key']}", "X-Workspace-ID": ws["id"]}
    await client.get("/api/v1/members", headers=key_headers)
    await client.get("/api/v1/members", headers=key_headers)

    listed = (await client.get("/api/v1/api-keys", headers=headers)).json()
    item = next(k for k in listed if k["id"] == created["id"])
    assert item["usage_count"] == 2


async def test_key_quota_enforced(app_client):
    client = app_client
    owner = await register_user(client, "xena@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    created = (
        await client.post(
            "/api/v1/api-keys",
            json={"name": "capped", "permissions": ["member:read"], "usage_quota": 1},
            headers=headers,
        )
    ).json()
    assert created["usage_quota"] == 1

    key_headers = {"Authorization": f"Bearer {created['key']}", "X-Workspace-ID": ws["id"]}
    first = await client.get("/api/v1/members", headers=key_headers)
    assert first.status_code == 200
    assert first.headers["X-API-Key-Quota"] == "1"
    assert first.headers["X-API-Key-Remaining"] == "0"

    # quota exhausted → 403 without touching usage further
    resp = await client.get("/api/v1/members", headers=key_headers)
    assert resp.status_code == 403
    assert "quota" in resp.json()["detail"].lower()

    # raising the quota unblocks the key
    patched = await client.patch(
        f"/api/v1/api-keys/{created['id']}",
        json={"usage_quota": 5},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["usage_quota"] == 5
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200

    # clearing the quota (None) means unlimited
    cleared = await client.patch(
        f"/api/v1/api-keys/{created['id']}",
        json={"usage_quota": None},
        headers=headers,
    )
    assert cleared.json()["usage_quota"] is None


async def test_quota_patch_scoped_to_owner(app_client):
    client = app_client
    owner = await register_user(client, "willa@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    created = (
        await client.post(
            "/api/v1/api-keys", json={"name": "mine", "permissions": []}, headers=headers
        )
    ).json()

    # an editor member of the same workspace still cannot touch another user's key
    roles = (await client.get("/api/v1/roles", headers=headers)).json()
    editor = next(r for r in roles if r["name"] == "editor")
    member = await register_user(client, "xara@example.com")
    invite = (
        await client.post(
            "/api/v1/invitations",
            json={"email": "xara@example.com", "role_id": editor["id"]},
            headers=headers,
        )
    ).json()
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(member),
    )
    resp = await client.patch(
        f"/api/v1/api-keys/{created['id']}",
        json={"usage_quota": 10},
        headers=ws_headers(member, ws["id"]),
    )
    assert resp.status_code == 404  # not leaked across users


async def test_quota_patch_validates_and_scopes_to_owner(app_client):
    client = app_client
    owner = await register_user(client, "yara@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    created = (
        await client.post(
            "/api/v1/api-keys", json={"name": "q", "permissions": []}, headers=headers
        )
    ).json()

    resp = await client.patch(
        f"/api/v1/api-keys/{created['id']}",
        json={"usage_quota": -1},
        headers=headers,
    )
    assert resp.status_code == 422

    stranger = await register_user(client, "zane@example.com")
    resp = await client.patch(
        f"/api/v1/api-keys/{created['id']}",
        json={"usage_quota": 10},
        headers=auth_headers(stranger),
    )
    assert resp.status_code in (400, 403)  # no workspace scope, no membership
