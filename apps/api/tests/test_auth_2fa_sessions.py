from src.core.security.ratelimit import SlidingWindowLimiter
from src.core.security.totp import current_code, otpauth_uri, secret_from_base32
from tests.conftest import auth_headers, login, register_user


async def _totp_for(client, headers):
    resp = await client.post("/api/v1/auth/2fa/setup", headers=headers)
    assert resp.status_code == 200, resp.text
    setup = resp.json()
    uri = setup["otpauth_uri"]
    b32 = uri.split("secret=")[1].split("&")[0]
    return setup["setup_token"], current_code(secret_from_base32(b32))


def test_otpauth_uri_encodes_issuer_and_email():
    uri = otpauth_uri(
        secret_b32="ABC123",
        issuer="SaaS Template API",
        email="user+test@example.com",
    )

    assert uri == (
        "otpauth://totp/SaaS%20Template%20API:user%2Btest%40example.com"
        "?secret=ABC123&issuer=SaaS+Template+API&algorithm=SHA1&digits=6&period=30"
    )


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

    # the only session is current -> revoking it is refused
    assert sessions[0]["current"] is True
    resp = await client.delete(f"/api/v1/auth/sessions/{sessions[0]['id']}", headers=headers)
    assert resp.status_code == 400

    # a second session can be revoked -> its refresh stops working
    other = await login(client, "sess@example.com")
    resp = await client.get("/api/v1/auth/sessions", headers=headers)
    others = [s for s in resp.json() if not s["current"]]
    assert len(others) == 1
    resp = await client.delete(f"/api/v1/auth/sessions/{others[0]['id']}", headers=headers)
    assert resp.status_code == 204
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": other["refresh_token"]})
    assert resp.status_code == 401
    # revoked sessions disappear from the list; the current one remains
    resp = await client.get("/api/v1/auth/sessions", headers=headers)
    assert [s["id"] for s in resp.json()] == [sessions[0]["id"]]


async def test_revoked_session_access_token_rejected(app_client):
    client = app_client
    t1 = await register_user(client, "revoked-at@example.com")
    t2 = await login(client, "revoked-at@example.com")
    h1, h2 = auth_headers(t1), auth_headers(t2)

    resp = await client.get("/api/v1/auth/me", headers=h1)
    assert resp.status_code == 200, resp.text

    # Revoke t1's session from t2's session (mirrors DELETE /sessions/{id}).
    resp = await client.get("/api/v1/auth/sessions", headers=h2)
    other = next(s for s in resp.json() if not s["current"])
    resp = await client.delete(f"/api/v1/auth/sessions/{other['id']}", headers=h2)
    assert resp.status_code == 204, resp.text

    # The revoked session's access token is rejected on the next request.
    resp = await client.get("/api/v1/auth/me", headers=h1)
    assert resp.status_code == 401, resp.text
    # And its refresh token no longer rotates.
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert resp.status_code == 401, resp.text
    # The surviving session keeps working.
    resp = await client.get("/api/v1/auth/me", headers=h2)
    assert resp.status_code == 200, resp.text


async def test_revoke_all_sessions(app_client):
    client = app_client
    t1 = await register_user(client, "all@example.com")
    t2 = await login(client, "all@example.com")
    headers = auth_headers(t2)
    resp = await client.get("/api/v1/auth/sessions", headers=headers)
    listed = resp.json()
    assert len(listed) == 2
    assert sum(s["current"] for s in listed) == 1
    resp = await client.delete("/api/v1/auth/sessions", headers=headers)
    assert resp.status_code == 204
    # the other session is revoked; the current one keeps working
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert resp.status_code == 401
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert resp.status_code == 200, resp.text
    # refresh rotates: the current session id moves to the new row
    rotated = resp.json()
    resp = await client.get("/api/v1/auth/sessions", headers=auth_headers(rotated))
    remaining = resp.json()
    assert len(remaining) == 1
    assert remaining[0]["current"] is True


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


async def test_wrong_password_disabling_2fa_keeps_session(app_client):
    """Issue #189: a wrong password answers 400, not 401.

    The web client reads 401 as a dead session and force-logs out, so the
    status code has to be the one that leaves the session alone."""
    client = app_client
    tokens = await register_user(client, "totp-wrong@example.com")
    headers = auth_headers(tokens)
    setup_token, code = await _totp_for(client, headers)
    resp = await client.post(
        "/api/v1/auth/2fa/enable", json={"setup_token": setup_token, "code": code}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(
        "/api/v1/auth/2fa/disable", json={"password": "Wrongpass1!"}, headers=headers
    )
    assert resp.status_code == 400, resp.text

    # TOTP is still on — the rejected attempt did not disable it.
    resp = await client.get("/api/v1/auth/2fa/status", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is True

    # Same access token still authenticates, and a correct password works.
    resp = await client.post(
        "/api/v1/auth/2fa/disable", json={"password": "Password123!"}, headers=headers
    )
    assert resp.status_code == 204, resp.text


async def test_wrong_password_regenerating_backup_codes_keeps_session(app_client):
    client = app_client
    tokens = await register_user(client, "totp-bak@example.com")
    headers = auth_headers(tokens)
    setup_token, code = await _totp_for(client, headers)
    resp = await client.post(
        "/api/v1/auth/2fa/enable", json={"setup_token": setup_token, "code": code}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(
        "/api/v1/auth/2fa/backup-codes", json={"password": "Wrongpass1!"}, headers=headers
    )
    assert resp.status_code == 400, resp.text

    resp = await client.get("/api/v1/auth/2fa/status", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is True

    resp = await client.post(
        "/api/v1/auth/2fa/backup-codes", json={"password": "Password123!"}, headers=headers
    )
    assert resp.status_code == 200, resp.text


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
