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
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert resp.status_code == 401, resp.text
    resp = await client.get("/api/v1/auth/me", headers=h2)
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
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert resp.status_code == 401
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
