from tests.conftest import auth_headers, login, register_user


async def test_register_login_me_flow(app_client):
    client = app_client
    tokens = await register_user(client, "alice@example.com")
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    login_tokens = await login(client, "alice@example.com")
    assert login_tokens["access_token"]

    me = await client.get("/api/v1/auth/me", headers=auth_headers(login_tokens))
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "alice@example.com"
    assert body["workspaces"] == []
    assert body["permissions"] == []


async def test_login_wrong_password(app_client):
    await register_user(client=app_client, email="bob@example.com")
    resp = await app_client.post(
        "/api/v1/auth/login", json={"email": "bob@example.com", "password": "WrongPass123!"}
    )
    assert resp.status_code == 401


async def test_refresh_rotation(app_client):
    client = app_client
    tokens = await register_user(client, "carol@example.com")
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200
    rotated = resp.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]

    # old token must now be rejected
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 401


async def test_protected_route_requires_token(app_client):
    resp = await app_client.get("/api/v1/auth/me")
    assert resp.status_code == 401
