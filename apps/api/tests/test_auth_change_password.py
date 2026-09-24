"""Change password (issue #174): current password always, 2FA code when on."""

from tests.conftest import auth_headers, login, register_user


async def test_wrong_current_password_401(app_client):
    client = app_client
    tokens = await register_user(client, "chg@example.com")
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Wrongpass1!", "new_password": "Newpass123!"},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 401, resp.text


async def test_success_revokes_all_sessions_and_rotates_password(app_client):
    client = app_client
    t1 = await register_user(client, "chg2@example.com")
    t2 = await login(client, "chg2@example.com")
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Password123!", "new_password": "Newpass123!"},
        headers=auth_headers(t2),
    )
    assert resp.status_code == 204, resp.text
    # both refresh tokens dead (current session revoked too)
    for t in (t1, t2):
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})
        assert r.status_code == 401, r.text
    # old password dead, new password works
    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": "chg2@example.com", "password": "Password123!"},
    )
    assert bad.status_code == 401, bad.text
    good = await client.post(
        "/api/v1/auth/login",
        json={"email": "chg2@example.com", "password": "Newpass123!"},
    )
    assert good.status_code == 200, good.text


async def test_2fa_user_needs_code(app_client):
    from src.core.security.totp import current_code, secret_from_base32

    client = app_client
    tokens = await register_user(client, "chg3@example.com")
    headers = auth_headers(tokens)
    resp = await client.post("/api/v1/auth/2fa/setup", headers=headers)
    assert resp.status_code == 200, resp.text
    setup = resp.json()
    b32 = setup["otpauth_uri"].split("secret=")[1].split("&")[0]
    code = current_code(secret_from_base32(b32))
    en = await client.post(
        "/api/v1/auth/2fa/enable",
        json={"setup_token": setup["setup_token"], "code": code},
        headers=headers,
    )
    assert en.status_code == 200, en.text
    backup = en.json()["backup_codes"][0]

    # no code -> 401
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Password123!", "new_password": "Newpass123!"},
        headers=headers,
    )
    assert resp.status_code == 401, resp.text
    # wrong code -> 401
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "Password123!",
            "new_password": "Newpass123!",
            "code": "000000",
        },
        headers=headers,
    )
    assert resp.status_code == 401, resp.text
    # backup code (single-use) -> 204. Same counter can't be reused: verify()
    # enforces replay protection via last_counter, so TOTP codes only work once.
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "Password123!",
            "new_password": "Newpass123!",
            "code": backup,
        },
        headers=headers,
    )
    assert resp.status_code == 204, resp.text
