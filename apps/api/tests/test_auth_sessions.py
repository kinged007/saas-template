from tests.conftest import auth_headers, login, register_user


async def test_revoked_session_access_token_rejected(app_client):
    client = app_client
    t1 = await register_user(client, "revoked-at@example.com")
    t2 = await login(client, "revoked-at@example.com")
    h1, h2 = auth_headers(t1), auth_headers(t2)

    resp = await client.get("/api/v1/auth/me", headers=h1)
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/auth/sessions", headers=h2)
    assert resp.status_code == 200, resp.text
    other = next(s for s in resp.json() if not s["current"])
    resp = await client.delete(f"/api/v1/auth/sessions/{other['id']}", headers=h2)
    assert resp.status_code == 204, resp.text

    resp = await client.get("/api/v1/auth/me", headers=h1)
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "session revoked"
    # the surviving session keeps working until the revoked token is replayed
    resp = await client.get("/api/v1/auth/me", headers=h2)
    assert resp.status_code == 200, resp.text
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert resp.status_code == 401, resp.text
    # replaying it is refresh-token reuse: the surviving session goes too
    resp = await client.get("/api/v1/auth/me", headers=h2)
    assert resp.status_code == 401, resp.text


async def test_session_routes_reject_api_key_callers(app_client):
    from tests.conftest import create_workspace

    client = app_client
    tokens = await register_user(client, "sesskey@example.com")
    workspace = await create_workspace(client, tokens)
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "k", "permissions": ["*"]},
        headers={**auth_headers(tokens), "X-Workspace-ID": workspace["id"]},
    )
    assert resp.status_code == 201, resp.text
    key_headers = {
        "Authorization": f"Bearer {resp.json()['key']}",
        "X-Workspace-ID": workspace["id"],
    }
    resp = await client.get("/api/v1/auth/sessions", headers=key_headers)
    assert resp.status_code == 403, resp.text
    resp = await client.delete("/api/v1/auth/sessions", headers=key_headers)
    assert resp.status_code == 403, resp.text
    resp = await client.delete("/api/v1/auth/sessions/anything", headers=key_headers)
    assert resp.status_code == 403, resp.text


async def test_reused_refresh_token_revokes_all_sessions(app_client):
    client = app_client
    t1 = await register_user(client, "reuse@example.com")
    t2 = await login(client, "reuse@example.com")

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert resp.status_code == 200, resp.text
    rotated = resp.json()

    # replaying an already-rotated token is a compromise signal
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "invalid refresh token"

    # every live session of that user is revoked
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert resp.status_code == 401, resp.text
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert resp.status_code == 401, resp.text
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(rotated))
    assert resp.status_code == 401, resp.text


async def test_unknown_refresh_token_revokes_nothing(app_client):
    client = app_client
    t1 = await register_user(client, "unknown@example.com")
    t2 = await login(client, "unknown@example.com")

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert resp.status_code == 401, resp.text

    resp = await client.get("/api/v1/auth/me", headers=auth_headers(t1))
    assert resp.status_code == 200, resp.text
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert resp.status_code == 200, resp.text


async def test_reused_refresh_token_does_not_lock_the_account(app_client):
    client = app_client
    t1 = await register_user(client, "reuse-login@example.com")
    t2 = await login(client, "reuse-login@example.com")

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert resp.status_code == 200, resp.text
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert resp.status_code == 401, resp.text

    # signed out, not disabled
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(t1))
    assert resp.status_code == 401, resp.text
    t3 = await login(client, "reuse-login@example.com")
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(t3))
    assert resp.status_code == 200, resp.text


async def test_revoke_all_sessions(app_client):
    client = app_client
    t1 = await register_user(client, "all@example.com")
    t2 = await login(client, "all@example.com")
    headers = auth_headers(t2)
    resp = await client.get("/api/v1/auth/sessions", headers=headers)
    assert resp.status_code == 200, resp.text
    listed = resp.json()
    assert len(listed) == 2
    assert sum(s["current"] for s in listed) == 1
    # revoking the current session alone is refused
    current = next(s for s in listed if s["current"])
    resp = await client.delete(f"/api/v1/auth/sessions/{current['id']}", headers=headers)
    assert resp.status_code == 400, resp.text
    resp = await client.delete("/api/v1/auth/sessions", headers=headers)
    assert resp.status_code == 204
    # the revoked session's access token 401s on the next request
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(t1))
    assert resp.status_code == 401, resp.text
    # the calling session survives
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert resp.status_code == 200, resp.text
    rotated = resp.json()
    resp = await client.get("/api/v1/auth/sessions", headers=auth_headers(rotated))
    remaining = resp.json()
    assert len(remaining) == 1
    assert remaining[0]["current"] is True
    # replaying the revoked token is reuse, and takes the surviving session too
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert resp.status_code == 401
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert resp.status_code == 401
