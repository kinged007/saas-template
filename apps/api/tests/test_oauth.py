"""OAuth/SSO login + registration/password kill-switches. No network: provider
exchanges are monkeypatched at the service-module boundary."""

import json

import pytest
from sqlalchemy import func, select

from src.db.session import SessionFactory
from src.models.workspace import User
from src.services import oauth as oauth_svc
from src.settings import settings
from tests.conftest import auth_headers, register_user

PROVIDERS = [
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


@pytest.fixture
def oauth_on(monkeypatch):
    monkeypatch.setattr(settings, "oauth_providers", json.dumps(PROVIDERS))
    monkeypatch.setattr(settings, "auth_allow_registration", True)
    monkeypatch.setattr(settings, "auth_password_enabled", True)
    yield
    monkeypatch.setattr(settings, "oauth_providers", "")
    monkeypatch.setattr(settings, "auth_allow_registration", True)
    monkeypatch.setattr(settings, "auth_password_enabled", True)


async def _user_count() -> int:
    async with SessionFactory() as s:
        return (await s.execute(select(func.count()).select_from(User))).scalar_one()


async def test_config_reflects_flags(app_client, oauth_on, monkeypatch):
    resp = await app_client.get("/api/v1/auth/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["registration_enabled"] is True
    assert body["password_enabled"] is True
    assert body["oauth_enabled"] is True
    assert body["providers"] == [{"id": "testidp", "display_name": "Test IdP"}]
    monkeypatch.setattr(settings, "auth_allow_registration", False)
    monkeypatch.setattr(settings, "auth_password_enabled", False)
    monkeypatch.setattr(settings, "oauth_providers", "")
    resp = await app_client.get("/api/v1/auth/config")
    body = resp.json()
    assert body == {
        "registration_enabled": False,
        "password_enabled": False,
        "oauth_enabled": False,
        "providers": [],
    }


async def test_authorize_redirects_with_state(app_client, oauth_on):
    resp = await app_client.get("/api/v1/auth/oauth/testidp/authorize", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://idp.example/authorize?")
    assert "state=" in resp.headers["location"]


async def test_unknown_provider_404(app_client, oauth_on):
    resp = await app_client.get("/api/v1/auth/oauth/nope/authorize", follow_redirects=False)
    assert resp.status_code == 404


def _mock_oauth(monkeypatch, *, sub="sub-1", email="sso@example.com"):
    async def fake_discovery(provider, cache):
        return {
            "authorization_endpoint": provider.authorize_url,
            "token_endpoint": provider.token_url,
            "userinfo_endpoint": provider.userinfo_url,
        }

    async def fake_exchange(provider, doc, *, code, redirect_uri):
        assert code == "authcode"
        return {"access_token": "at", "id_token": None}

    async def fake_userinfo(provider, doc, access_token):
        return {"sub": sub, "email": email, "name": "Sso User"}

    monkeypatch.setattr(oauth_svc, "_discovery", fake_discovery)
    import src.api.routes.oauth as oauth_routes

    monkeypatch.setattr(oauth_routes, "exchange_code", fake_exchange)
    monkeypatch.setattr(oauth_routes, "fetch_userinfo", fake_userinfo)


async def _callback(app_client, monkeypatch, state="s"):
    # Seed a valid state entry the way /authorize would.
    import src.api.routes.oauth as oauth_routes

    monkeypatch.setattr(oauth_routes, "_redirect_uri", lambda req, pid: "http://test/cb")
    from src.main import app as fastapi_app

    fastapi_app.state.container.cache.set(
        oauth_svc.STATE_TTL_HINT + state, {"provider": "testidp", "redirect_uri": "http://test/cb"}
    )
    resp = await app_client.get(
        f"/api/v1/auth/oauth/testidp/callback?code=authcode&state={state}",
        follow_redirects=False,
    )
    return fastapi_app.state.container.cache, resp


async def test_oauth_new_user_allowed(app_client, oauth_on, monkeypatch):
    _mock_oauth(monkeypatch)
    before = await _user_count()
    _, resp = await _callback(app_client, monkeypatch)
    assert resp.status_code == 302, resp.text
    assert resp.headers["location"].startswith("http://localhost:5173/oauth/callback?code=")
    assert await _user_count() == before + 1
    code = resp.headers["location"].split("code=")[1]
    tokens = await app_client.post("/api/v1/auth/oauth/token", json={"code": code})
    assert tokens.status_code == 200, tokens.text
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens.json()))
    assert me.status_code == 200
    assert me.json()["email"] == "sso@example.com"
    # Reuse is rejected (single-use code).
    again = await app_client.post("/api/v1/auth/oauth/token", json={"code": code})
    assert again.status_code == 400


async def test_oauth_existing_user_links_by_subject(app_client, oauth_on, monkeypatch):
    _mock_oauth(monkeypatch)
    _, first = await _callback(app_client, monkeypatch, state="s1")
    assert first.status_code == 302
    before = await _user_count()
    _, second = await _callback(app_client, monkeypatch, state="s2")
    assert second.status_code == 302
    assert await _user_count() == before  # linked, not duplicated


async def test_oauth_multi_provider_same_email_links(app_client, oauth_on, monkeypatch):
    _mock_oauth(monkeypatch)
    _, first = await _callback(app_client, monkeypatch, state="s1")
    assert first.status_code == 302
    before = await _user_count()
    # Same email from a different subject still links to the same user.
    _mock_oauth(monkeypatch, sub="sub-other")
    _, second = await _callback(app_client, monkeypatch, state="s2")
    assert second.status_code == 302
    assert await _user_count() == before


async def test_oauth_new_user_blocked_when_registration_disabled(app_client, oauth_on, monkeypatch):
    _mock_oauth(monkeypatch, email="newblocked@example.com")
    monkeypatch.setattr(settings, "auth_allow_registration", False)
    before = await _user_count()
    _, resp = await _callback(app_client, monkeypatch)
    assert resp.status_code == 302
    assert "registration" in resp.headers["location"]
    assert await _user_count() == before


async def test_oauth_existing_user_logs_in_when_registration_disabled(
    app_client, oauth_on, monkeypatch
):
    _mock_oauth(monkeypatch)
    _, first = await _callback(app_client, monkeypatch, state="s1")
    assert first.status_code == 302
    monkeypatch.setattr(settings, "auth_allow_registration", False)
    before = await _user_count()
    _, second = await _callback(app_client, monkeypatch, state="s2")
    assert second.status_code == 302
    assert "/oauth/callback?code=" in second.headers["location"]
    assert await _user_count() == before


async def test_callback_bad_state_redirects_to_login(app_client, oauth_on):
    resp = await app_client.get(
        "/api/v1/auth/oauth/testidp/callback?code=x&state=bogus", follow_redirects=False
    )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("http://localhost:5173/login?error=")


async def test_register_blocked_when_disabled(app_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_allow_registration", False)
    try:
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={
                "email": "n@n.com",
                "password": "Password123!",
                "first_name": "N",
                "last_name": "N",
            },
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "registration is disabled"
    finally:
        monkeypatch.setattr(settings, "auth_allow_registration", True)


async def test_password_login_blocked_when_disabled(app_client, monkeypatch):
    await register_user(app_client, "pw@example.com")
    monkeypatch.setattr(settings, "auth_password_enabled", False)
    try:
        resp = await app_client.post(
            "/api/v1/auth/login", json={"email": "pw@example.com", "password": "Password123!"}
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "password login is disabled"
    finally:
        monkeypatch.setattr(settings, "auth_password_enabled", True)


async def test_password_reset_blocked_when_password_disabled(app_client, monkeypatch):
    await register_user(app_client, "nopw@example.com")
    monkeypatch.setattr(settings, "auth_password_enabled", False)
    try:
        resp = await app_client.post(
            "/api/v1/auth/forgot-password", json={"email": "nopw@example.com"}
        )
        assert resp.status_code == 202  # shape kept, no token minted
        resp = await app_client.post(
            "/api/v1/auth/reset-password",
            json={"token": "bogus", "new_password": "NewPassword123!"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "password login is disabled"
    finally:
        monkeypatch.setattr(settings, "auth_password_enabled", True)


async def test_oauth_error_redirect_allowlisted(app_client, oauth_on):
    resp = await app_client.get(
        "/api/v1/auth/oauth/testidp/callback?code=x&state=bogus", follow_redirects=False
    )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("http://localhost:5173/login?error=")
