"""Browser cookie session flow: HttpOnly refresh cookie + CSRF + dual-mode."""

import pytest

from src.settings import settings
from tests.conftest import auth_headers, register_user

CSRF = {"X-Requested-With": "XMLHttpRequest"}


def _cookie_name() -> str:
    return settings.refresh_cookie_name


def _set_cookie(resp) -> str:
    raw = resp.headers.get("set-cookie", "")
    assert _cookie_name() in raw, f"refresh cookie missing: {raw!r}"
    assert "HttpOnly" in raw, raw
    assert "SameSite=Lax" in raw or "SameSite=lax" in raw, raw
    assert "Path=/api/v1/auth" in raw, raw
    if settings.environment not in ("development", "test"):
        assert "Secure" in raw, raw
    return raw


async def test_login_cookie_flow_sets_cookie_and_omits_json_refresh(app_client):
    await register_user(app_client, "cookie1@example.com")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "cookie1@example.com", "password": "Password123!", "use_cookies": True},
    )
    assert resp.status_code == 200, resp.text
    _set_cookie(resp)
    body = resp.json()
    assert body["access_token"]
    assert body.get("refresh_token") is None


async def test_register_cookie_flow_omits_json_refresh(app_client):
    resp = await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "cookie-reg@example.com",
            "password": "Password123!",
            "first_name": "C",
            "last_name": "R",
            "use_cookies": True,
        },
    )
    assert resp.status_code == 201, resp.text
    _set_cookie(resp)
    assert resp.json().get("refresh_token") is None


async def test_json_flow_still_returns_refresh(app_client):
    tokens = await register_user(app_client, "json1@example.com")
    assert tokens["refresh_token"]
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "json1@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 200
    assert resp.json()["refresh_token"]
    assert _cookie_name() not in resp.headers.get("set-cookie", "")


async def test_header_opt_in_sets_cookie(app_client):
    await register_user(app_client, "hdr1@example.com")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "hdr1@example.com", "password": "Password123!"},
        headers={"X-Session-Flow": "cookie"},
    )
    assert resp.status_code == 200, resp.text
    _set_cookie(resp)
    assert resp.json().get("refresh_token") is None


async def test_query_param_opt_in_sets_cookie(app_client):
    await register_user(app_client, "qp1@example.com")
    resp = await app_client.post(
        "/api/v1/auth/login?use_cookies=true",
        json={"email": "qp1@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 200, resp.text
    _set_cookie(resp)
    assert resp.json().get("refresh_token") is None


async def test_login_without_opt_in_does_not_set_cookie(app_client):
    await register_user(app_client, "json2@example.com")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "json2@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 200
    assert _cookie_name() not in resp.headers.get("set-cookie", "")


async def test_refresh_via_cookie_rotates(app_client):
    await register_user(app_client, "cookie2@example.com")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "cookie2@example.com", "password": "Password123!", "use_cookies": True},
    )
    assert resp.status_code == 200, resp.text
    # httpx AsyncClient keeps the cookie jar; refresh with no body.
    r2 = await app_client.post("/api/v1/auth/refresh", json={}, headers=CSRF)
    assert r2.status_code == 200, r2.text
    _set_cookie(r2)
    assert r2.json().get("refresh_token") is None
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(r2.json()))
    assert me.status_code == 200


async def test_refresh_needs_either_cookie_or_body(app_client):
    resp = await app_client.post("/api/v1/auth/refresh", json={})
    assert resp.status_code == 401


async def test_json_refresh_still_works(app_client):
    tokens = await register_user(app_client, "json3@example.com")
    resp = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["refresh_token"] != tokens["refresh_token"]
    assert _cookie_name() not in resp.headers.get("set-cookie", "")


async def test_refresh_rejects_forged_origin(app_client):
    await register_user(app_client, "cookie3@example.com")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "cookie3@example.com", "password": "Password123!", "use_cookies": True},
    )
    assert resp.status_code == 200
    bad = dict(CSRF)
    bad["Origin"] = "https://evil.test"
    r = await app_client.post("/api/v1/auth/refresh", json={}, headers=bad)
    assert r.status_code == 403, r.text


async def test_refresh_rejects_missing_csrf_header(app_client):
    await register_user(app_client, "cookie4@example.com")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "cookie4@example.com", "password": "Password123!", "use_cookies": True},
    )
    assert resp.status_code == 200
    r = await app_client.post("/api/v1/auth/refresh", json={})
    assert r.status_code == 403, r.text


async def test_refresh_accepts_same_origin(app_client):
    await register_user(app_client, "cookie5@example.com")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "cookie5@example.com", "password": "Password123!", "use_cookies": True},
    )
    assert resp.status_code == 200
    ok = dict(CSRF)
    ok["Origin"] = "http://localhost:5173"
    r = await app_client.post("/api/v1/auth/refresh", json={}, headers=ok)
    assert r.status_code == 200, r.text


async def test_2fa_cookie_login_omits_json_refresh(app_client):
    from src.core.security.totp import current_code, secret_from_base32

    await register_user(app_client, "cookie2fa@example.com")
    login_resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "cookie2fa@example.com", "password": "Password123!"},
    )
    headers = auth_headers(login_resp.json())
    setup = (await app_client.post("/api/v1/auth/2fa/setup", headers=headers)).json()
    b32 = setup["otpauth_uri"].split("secret=")[1].split("&")[0]
    code = current_code(secret_from_base32(b32))
    resp = await app_client.post(
        "/api/v1/auth/2fa/enable",
        json={"setup_token": setup["setup_token"], "code": code},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    backup_codes = resp.json()["backup_codes"]
    challenge = (
        await app_client.post(
            "/api/v1/auth/login",
            json={"email": "cookie2fa@example.com", "password": "Password123!"},
        )
    ).json()["detail"]["challenge_token"]
    # The TOTP code was already consumed by /2fa/enable's replay window;
    # use a single-use backup code for the cookie login.
    r = await app_client.post(
        "/api/v1/auth/2fa/login",
        json={"challenge_token": challenge, "code": backup_codes[0], "use_cookies": True},
    )
    assert r.status_code == 200, r.text
    _set_cookie(r)
    assert r.json().get("refresh_token") is None


async def test_logout_clears_cookie(app_client):
    await register_user(app_client, "cookie6@example.com")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "cookie6@example.com", "password": "Password123!", "use_cookies": True},
    )
    assert resp.status_code == 200
    r = await app_client.post("/api/v1/auth/logout", json={}, headers=CSRF)
    assert r.status_code == 204, r.text
    cleared = r.headers.get("set-cookie", "")
    assert _cookie_name() in cleared, cleared
    # Cookie was revoked server-side: refresh now fails.
    r2 = await app_client.post("/api/v1/auth/refresh", json={}, headers=CSRF)
    assert r2.status_code == 401


async def test_oauth_token_cookie_flow_omits_json_refresh(app_client, monkeypatch):
    import json as _json

    from src.services import oauth as oauth_svc

    monkeypatch.setattr(
        settings,
        "oauth_providers",
        _json.dumps(
            [
                {
                    "id": "testidp",
                    "display_name": "Test IdP",
                    "authorize_url": "https://idp.example/authorize",
                    "token_url": "https://idp.example/token",
                    "userinfo_url": "https://idp.example/userinfo",
                    "client_id": "cid",
                    "client_secret": "csecret",
                }
            ]
        ),
    )
    try:
        import src.api.routes.oauth as oauth_routes
        from src.main import app as fastapi_app

        async def fake_discovery(provider, cache):
            return {
                "authorization_endpoint": provider.authorize_url,
                "token_endpoint": provider.token_url,
                "userinfo_endpoint": provider.userinfo_url,
            }

        async def fake_exchange(provider, doc, *, code, redirect_uri):
            return {"access_token": "at", "id_token": None}

        async def fake_userinfo(provider, doc, access_token):
            return {"sub": "cookie-sub", "email": "cookie-sso@example.com", "name": "C S"}

        monkeypatch.setattr(oauth_svc, "_discovery", fake_discovery)
        monkeypatch.setattr(oauth_routes, "exchange_code", fake_exchange)
        monkeypatch.setattr(oauth_routes, "fetch_userinfo", fake_userinfo)
        monkeypatch.setattr(oauth_routes, "_redirect_uri", lambda req, pid: "http://test/cb")
        fastapi_app.state.container.cache.set(
            oauth_svc.STATE_TTL_HINT + "s-cookie",
            {"provider": "testidp", "redirect_uri": "http://test/cb"},
        )
        cb = await app_client.get(
            "/api/v1/auth/oauth/testidp/callback?code=authcode&state=s-cookie",
            follow_redirects=False,
        )
        assert cb.status_code == 302, cb.text
        code = cb.headers["location"].split("code=")[1]
        tokens = await app_client.post(
            "/api/v1/auth/oauth/token", json={"code": code, "use_cookies": True}
        )
        assert tokens.status_code == 200, tokens.text
        _set_cookie(tokens)
        assert tokens.json().get("refresh_token") is None
        assert tokens.json()["access_token"]
        # The parked refresh moved into the cookie untouched: the cookie jar
        # holds a live session — refresh via cookie works.
        r2 = await app_client.post("/api/v1/auth/refresh", json={}, headers=CSRF)
        assert r2.status_code == 200, r2.text
        _set_cookie(r2)
        # The parked refresh was consumed server-side: replay rejected.
        again = await app_client.post("/api/v1/auth/oauth/token", json={"code": code})
        assert again.status_code == 400
    finally:
        monkeypatch.setattr(settings, "oauth_providers", "")


async def test_cookie_secure_follows_forwarded_proto(app_client):
    """Secure set on https (forwarded-proto) even with ENVIRONMENT=development."""
    await register_user(app_client, "fwdproto@example.com")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "fwdproto@example.com", "password": "Password123!", "use_cookies": True},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert resp.status_code == 200, resp.text
    assert "Secure" in resp.headers.get("set-cookie", ""), resp.headers.get("set-cookie")
    plain = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "fwdproto@example.com", "password": "Password123!"},
    )
    assert plain.status_code == 200, plain.text
    assert "Secure" not in plain.headers.get("set-cookie", "")


def _plain_request(headers: dict[str, str] | None = None, scheme: str = "http"):
    from fastapi import Request

    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": scheme,
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "client": ("test", 1),
            "server": ("testserver", 80),
        }
    )


async def test_cookie_secure_follows_forwarded_host_port(app_client):
    """Retained :443 host fallback, for a proxy that forwards the host only."""
    await register_user(app_client, "fwdhost@example.com")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "fwdhost@example.com", "password": "Password123!", "use_cookies": True},
        headers={"X-Forwarded-Host": "example.com:443"},
    )
    assert resp.status_code == 200, resp.text
    assert "Secure" in resp.headers.get("set-cookie", ""), resp.headers.get("set-cookie")


def test_client_headers_can_only_add_secure():
    """The header reads are client-controlled: they must never strip Secure."""
    from src.core.security.cookies import cookie_secure_for

    assert cookie_secure_for(_plain_request({"x-forwarded-proto": "http"}, scheme="https")) is True
    assert cookie_secure_for(_plain_request({"x-forwarded-proto": "https"})) is True
    assert cookie_secure_for(_plain_request({"host": "example.com:443"})) is True


def test_set_refresh_cookie_requires_request():
    """Omitting request would silently restore the pre-#155 ENVIRONMENT flag."""
    from fastapi import Response

    from src.core.security.cookies import set_refresh_cookie

    with pytest.raises(TypeError):
        set_refresh_cookie(Response(), "token")


def test_cookie_secure_explicit_override_wins():
    from src.core.security.cookies import cookie_secure_for

    original = settings.refresh_cookie_secure
    try:
        settings.refresh_cookie_secure = False
        assert cookie_secure_for(_plain_request()) is False
        settings.refresh_cookie_secure = True
        assert cookie_secure_for(_plain_request()) is True
    finally:
        settings.refresh_cookie_secure = original
