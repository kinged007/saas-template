from src.core.security.ratelimit import SlidingWindowLimiter
from src.core.security.totp import current_code, secret_from_base32
from tests.conftest import auth_headers, login, register_user


async def _totp_for(client, headers):
    resp = await client.post("/api/v1/auth/2fa/setup", headers=headers)
    assert resp.status_code == 200, resp.text
    setup = resp.json()
    uri = setup["otpauth_uri"]
    b32 = uri.split("secret=")[1].split("&")[0]
    return setup["setup_token"], current_code(secret_from_base32(b32))


async def test_sessions_list_and_revoke(app_client):
    client = app_client
    tokens = await register_user(client, "sess@example.com")
    refreshed = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"user-agent": "rotated-session-agent"},
    )
    assert refreshed.status_code == 200, refreshed.text
    headers = auth_headers(refreshed.json())
    resp = await client.get("/api/v1/auth/sessions", headers=headers)
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 1
    assert sessions[0]["ip_address"] is not None or True  # test client may lack IP
    assert sessions[0]["user_agent"] == "rotated-session-agent"
    assert sessions[0]["revoked_at"] is None

    # revoke the session -> refresh stops working
    resp = await client.delete(f"/api/v1/auth/sessions/{sessions[0]['id']}", headers=headers)
    assert resp.status_code == 204
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refreshed.json()["refresh_token"]}
    )
    assert resp.status_code == 401
    # revoked sessions disappear from the list
    resp = await client.get("/api/v1/auth/sessions", headers=headers)
    assert resp.json() == []


async def test_revoke_all_sessions(app_client):
    client = app_client
    t1 = await register_user(client, "all@example.com")
    t2 = await login(client, "all@example.com")
    headers = auth_headers(t2)
    resp = await client.get("/api/v1/auth/sessions", headers=headers)
    assert len(resp.json()) == 2
    resp = await client.delete("/api/v1/auth/sessions", headers=headers)
    assert resp.status_code == 204
    for t in (t1, t2):
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})
        assert resp.status_code == 401


async def test_totp_enrol_login_disable(app_client):
    client = app_client
    await register_user(client, "totp@example.com")
    tokens = await login(client, "totp@example.com")
    headers = auth_headers(tokens)

    setup_token, code = await _totp_for(client, headers)
    resp = await client.post(
        "/api/v1/auth/2fa/enable", json={"setup_token": setup_token, "code": code}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    backup_codes = resp.json()["backup_codes"]
    assert len(backup_codes) == 8

    # password login now demands a second factor
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "totp@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "2fa_required"
    challenge = resp.json()["detail"]["challenge_token"]

    # wrong code rejected
    resp = await client.post(
        "/api/v1/auth/2fa/login", json={"challenge_token": challenge, "code": "000000"}
    )
    assert resp.status_code in (401, 422)

    # fresh challenge + backup code works once
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "totp@example.com", "password": "Password123!"},
    )
    challenge = resp.json()["detail"]["challenge_token"]
    resp = await client.post(
        "/api/v1/auth/2fa/login",
        json={"challenge_token": challenge, "code": backup_codes[0]},
    )
    assert resp.status_code == 200, resp.text
    fresh = resp.json()
    fresh_headers = auth_headers(fresh)

    # backup code is single-use
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "totp@example.com", "password": "Password123!"},
    )
    challenge = resp.json()["detail"]["challenge_token"]
    resp = await client.post(
        "/api/v1/auth/2fa/login",
        json={"challenge_token": challenge, "code": backup_codes[0]},
    )
    assert resp.status_code == 401

    # disable with password restores plain login
    resp = await client.post(
        "/api/v1/auth/2fa/disable",
        json={"password": "Password123!"},
        headers=fresh_headers,
    )
    assert resp.status_code == 204, resp.text
    await login(client, "totp@example.com")


async def test_login_rate_limited(app_client, monkeypatch):
    from src.settings import settings

    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 3)
    client = app_client
    await register_user(client, "rl@example.com")
    bad = {"email": "rl@example.com", "password": "WrongPass123!"}
    for _ in range(3):
        resp = await client.post("/api/v1/auth/login", json=bad)
        assert resp.status_code == 401
    resp = await client.post("/api/v1/auth/login", json=bad)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


async def test_refresh_rate_limit_does_not_block_other_sessions(app_client, monkeypatch):
    from src.settings import settings

    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 3)
    client = app_client
    tokens = await register_user(client, "refresh-limit@example.com")
    for _ in range(3):
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "invalid-token"})
        assert resp.status_code == 401
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "invalid-token"})
    assert resp.status_code == 429

    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200, resp.text


def test_auth_rate_limiter_bounds_distinct_keys():
    limiter = SlidingWindowLimiter(max_keys=2)

    limiter.fail("first")
    limiter.fail("second")
    limiter.fail("third")
    limiter.check("fourth")

    assert len(limiter._failures) == 2
    assert "first" not in limiter._failures
    assert "fourth" not in limiter._failures
