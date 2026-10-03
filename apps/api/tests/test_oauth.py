"""OAuth/SSO login + registration/password kill-switches. No network: provider
exchanges are monkeypatched at the service-module boundary."""

import json
from dataclasses import replace

import httpx
import pytest
from sqlalchemy import func, select

from src.db.session import SessionFactory
from src.models.oauth import OAuthAccount
from src.models.workspace import User
from src.services import oauth as oauth_svc
from src.settings import settings
from tests.conftest import auth_headers, break_single_workspace_join, register_user

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

# GitHub is plain OAuth2: no discovery document, no id_token, and /user hides
# the address when the user keeps it private (emails_url carries it).
GITHUB = {
    "id": "github",
    "display_name": "GitHub",
    "authorize_url": "https://github.com/login/oauth/authorize",
    "token_url": "https://github.com/login/oauth/access_token",
    "userinfo_url": "https://api.github.com/user",
    "emails_url": "https://api.github.com/user/emails",
    "client_id": "cid",
    "client_secret": "csecret",
    "scopes": "read:user user:email",
}


class _Resp:
    def __init__(self, payload, url="https://provider.test/x", status=200):
        self._payload = payload
        self._request = httpx.Request("GET", url)
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self._status}",
                request=self._request,
                response=httpx.Response(self._status, request=self._request),
            )
        return None

    def json(self):
        return self._payload


class _EmailsClient:
    """One-shot httpx stand-in, so _verified_email can be called directly."""

    def __init__(self, payload, status_code=200):
        self._resp = _Resp(payload, status=status_code)

    async def get(self, url, headers=None):
        return self._resp


def _fake_httpx(
    monkeypatch,
    *,
    user,
    emails,
    user_status=200,
    emails_status=200,
    token_status=200,
    discovery_status=200,
):
    """Serve the token exchange, discovery, /user and /user/emails from literals;
    returns the URLs requested. emails=None marks that endpoint as off-limits. A
    *_status above 399 makes that endpoint answer with an error."""
    calls: list[str] = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            calls.append(url)
            return _Resp({"access_token": "at", "access_token_type": "bearer"}, url, token_status)

        async def get(self, url, **kwargs):
            calls.append(url)
            if ".well-known" in url:
                return _Resp({}, url, discovery_status)
            if url.endswith("/emails"):
                if emails is None:
                    raise AssertionError(f"emails endpoint must not be called ({url})")
                return _Resp(emails, url, emails_status)
            return _Resp(user, url, user_status)

    monkeypatch.setattr(oauth_svc.httpx, "AsyncClient", _Client)
    return calls


@pytest.fixture
def github_on(monkeypatch):
    monkeypatch.setattr(settings, "oauth_providers", json.dumps([GITHUB]))
    monkeypatch.setattr(settings, "auth_allow_registration", True)
    yield
    monkeypatch.setattr(settings, "oauth_providers", "")
    monkeypatch.setattr(settings, "auth_allow_registration", True)


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


async def _link_count() -> int:
    async with SessionFactory() as s:
        return (await s.execute(select(func.count()).select_from(OAuthAccount))).scalar_one()


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


def _mock_discovery(monkeypatch, doc):
    """Real fetch_userinfo / exchange_code against a canned discovery document."""

    async def fake_discovery(provider, cache):
        return dict(doc)

    async def fake_exchange(provider, doc, *, code, redirect_uri):
        return {"access_token": "at", "id_token": None}

    monkeypatch.setattr(oauth_svc, "_discovery", fake_discovery)
    import src.api.routes.oauth as oauth_routes

    monkeypatch.setattr(oauth_routes, "exchange_code", fake_exchange)


# A discovery-mode provider: no explicit endpoints, one anchor host (idp.example).
DISCOVERY = {
    "id": "oidcidp",
    "display_name": "OIDC IdP",
    "discovery_url": "https://idp.example/.well-known/openid-configuration",
    "emails_url": "https://userinfo.idp.example/user/emails",
    "client_id": "cid",
    "client_secret": "csecret",
}


@pytest.fixture
def oidc_on(monkeypatch):
    def _set(emails_url: str) -> None:
        monkeypatch.setattr(
            settings,
            "oauth_providers",
            json.dumps([{**DISCOVERY, "emails_url": emails_url}]),
        )
        monkeypatch.setattr(settings, "auth_allow_registration", True)

    _set(DISCOVERY["emails_url"])
    yield _set
    monkeypatch.setattr(settings, "oauth_providers", "")
    monkeypatch.setattr(settings, "auth_allow_registration", True)


async def _callback(app_client, monkeypatch, state="s", provider="testidp"):
    # Seed a valid state entry the way /authorize would.
    import src.api.routes.oauth as oauth_routes

    monkeypatch.setattr(oauth_routes, "_redirect_uri", lambda req, pid: "http://test/cb")
    from src.main import app as fastapi_app

    fastapi_app.state.container.cache.set(
        oauth_svc.STATE_TTL_HINT + state, {"provider": provider, "redirect_uri": "http://test/cb"}
    )
    resp = await app_client.get(
        f"/api/v1/auth/oauth/{provider}/callback?code=authcode&state={state}",
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


async def test_oauth_same_provider_new_subject_links_same_user(app_client, oauth_on, monkeypatch):
    _mock_oauth(monkeypatch)
    _, first = await _callback(app_client, monkeypatch, state="s1")
    assert first.status_code == 302
    before = await _user_count()
    # Same email from a different subject still links to the same user, which
    # leaves two rows under one (user_id, provider) -- the documented
    # one-to-many cardinality, not a duplicate user.
    _mock_oauth(monkeypatch, sub="sub-other")
    _, second = await _callback(app_client, monkeypatch, state="s2")
    assert second.status_code == 302
    assert await _user_count() == before
    assert await _link_count() == 2


async def test_oauth_callback_survives_join_failure(app_client, oauth_on, monkeypatch):
    # A failed join is log-only: the rollback it needs expires every loaded
    # instance, and reading the user for the log line would be a lazy load.
    monkeypatch.setattr(settings, "single_workspace", True)
    await break_single_workspace_join(app_client)
    _mock_oauth(monkeypatch)

    _, resp = await _callback(app_client, monkeypatch)
    assert resp.status_code == 302, resp.text
    assert resp.headers["location"].startswith("http://localhost:5173/oauth/callback?code=")
    code = resp.headers["location"].split("code=")[1]
    tokens = await app_client.post("/api/v1/auth/oauth/token", json={"code": code})
    assert tokens.status_code == 200, tokens.text
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens.json()))
    assert me.status_code == 200, me.text
    assert me.json()["workspaces"] == []


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


# A GitHub account with a private address: /user answers, with a null email.
_PRIVATE_GITHUB_USER = {"id": 4242, "login": "octocat", "email": None}


def _github_config() -> oauth_svc.ProviderConfig:
    return oauth_svc.ProviderConfig(
        id="github",
        display_name="GitHub",
        client_id="cid",
        client_secret="csecret",
        scopes="read:user user:email",
        userinfo_url="https://api.github.com/user",
        emails_url="https://api.github.com/user/emails",
    )


def test_failure_detail_without_a_response():
    """The no-response half of the helper: DNS, timeout and TLS failures never
    reach it through the other tests, which all drive a synthetic HTTPStatusError."""
    assert oauth_svc._failure_detail(httpx.ConnectError("boom")) == "ConnectError"


async def test_emails_404_scope_hint_survives_a_reworded_failure_detail(monkeypatch):
    """The 404 branch keys off the status, not off _failure_detail's wording."""
    _fake_httpx(monkeypatch, user=_PRIVATE_GITHUB_USER, emails=[], emails_status=404)
    monkeypatch.setattr(oauth_svc, "_failure_detail", lambda exc: "status 404, not found")
    with pytest.raises(oauth_svc.OAuthError) as err:
        await oauth_svc.fetch_userinfo(_github_config(), {}, "at")
    msg = str(err.value)
    assert "https://api.github.com/user/emails" in msg
    assert "user:email" in msg  # the scope hint still fires


async def test_exchange_failure_names_the_upstream_status(monkeypatch):
    _fake_httpx(monkeypatch, user={}, emails=[], token_status=400)
    cfg = replace(_github_config(), token_url="https://github.com/login/oauth/access_token")
    with pytest.raises(oauth_svc.OAuthError) as err:
        await oauth_svc.exchange_code(cfg, {}, code="c", redirect_uri="http://app.test/cb")
    msg = str(err.value)
    assert "code exchange failed" in msg
    assert "400" in msg  # expired code, clock skew or a wrong secret all land here


async def test_discovery_failure_names_the_upstream_status(monkeypatch):
    _fake_httpx(monkeypatch, user={}, emails=[], discovery_status=503)
    cfg = replace(_github_config(), discovery_url="https://github.com/.well-known/x", issuer=None)
    with pytest.raises(oauth_svc.OAuthError) as err:
        await oauth_svc._discovery(cfg, oauth_svc.TtlCache())
    msg = str(err.value)
    assert "could not load discovery document" in msg and "github" in msg
    assert "503" in msg


async def test_emails_404_names_the_endpoint_and_the_missing_scope(monkeypatch):
    _fake_httpx(monkeypatch, user=_PRIVATE_GITHUB_USER, emails=[], emails_status=404)
    with pytest.raises(oauth_svc.OAuthError) as err:
        await oauth_svc.fetch_userinfo(_github_config(), {}, "at")
    msg = str(err.value)
    assert "could not fetch user info" not in msg  # separable from a /user fault
    assert "github" in msg and "https://api.github.com/user/emails" in msg
    assert "404" in msg and "user:email" in msg


async def test_emails_500_is_not_reported_as_a_scope_problem(monkeypatch):
    _fake_httpx(monkeypatch, user=_PRIVATE_GITHUB_USER, emails=[], emails_status=500)
    with pytest.raises(oauth_svc.OAuthError) as err:
        await oauth_svc.fetch_userinfo(_github_config(), {}, "at")
    msg = str(err.value)
    assert "https://api.github.com/user/emails" in msg and "500" in msg
    assert "scope" not in msg


async def test_userinfo_failure_names_the_userinfo_endpoint(monkeypatch):
    _fake_httpx(monkeypatch, user={}, emails=[], user_status=500)
    with pytest.raises(oauth_svc.OAuthError) as err:
        await oauth_svc.fetch_userinfo(_github_config(), {}, "at")
    msg = str(err.value)
    assert "https://api.github.com/user" in msg and "500" in msg
    assert "/user/emails" not in msg


async def test_github_callback_uses_emails_endpoint_when_profile_email_null(
    app_client, github_on, monkeypatch
):
    calls = _fake_httpx(
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": None, "name": "The Octocat"},
        emails=[
            {"email": "alt@example.com", "primary": False, "verified": True},
            {"email": "Octo@Example.com", "primary": True, "verified": True},
        ],
    )
    before = await _user_count()
    _, resp = await _callback(app_client, monkeypatch, state="g1", provider="github")
    assert resp.status_code == 302
    assert "https://api.github.com/user/emails" in calls
    assert await _user_count() == before + 1
    tokens = await app_client.post(
        "/api/v1/auth/oauth/token", json={"code": resp.headers["location"].split("code=")[1]}
    )
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens.json()))
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "octo@example.com"  # primary, lowercased
    async with SessionFactory() as s:
        link = (
            await s.execute(select(OAuthAccount).where(OAuthAccount.provider == "github"))
        ).scalar_one()
    assert link.subject == "4242"  # numeric account id, not the login


async def test_github_refuses_unverified_email(app_client, github_on, monkeypatch):
    _fake_httpx(
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": None},
        emails=[{"email": "octo@example.com", "primary": True, "verified": False}],
    )
    before = await _user_count()
    _, resp = await _callback(app_client, monkeypatch, state="g2", provider="github")
    assert resp.headers["location"].startswith("http://localhost:5173/login?error=sign-in%20failed")
    assert await _user_count() == before


@pytest.mark.parametrize(
    ("payload", "status", "expected"),
    [
        # Payload is not a list: the guard returns "" instead of iterating
        # a non-iterable body into a TypeError.
        (None, 200, ""),
        # Provider errored: raise_for_status() propagates out of the helper.
        ({"message": "server error"}, 502, httpx.HTTPStatusError),
        # Several verified addresses, none primary: the provider's list order decides.
        (
            [
                {"email": "first@example.com", "primary": False, "verified": True},
                {"email": "second@example.com", "primary": False, "verified": True},
            ],
            200,
            "first@example.com",
        ),
    ],
    ids=["non-list-payload", "raise-for-status", "no-primary"],
)
async def test_verified_email_edge_branches(payload, status, expected):
    """The three _verified_email arms the callback tests never reach."""
    client = _EmailsClient(payload, status)
    if isinstance(expected, type):
        with pytest.raises(expected):
            await oauth_svc._verified_email(client, "https://api.github.com/user/emails", {})
    else:
        got = await oauth_svc._verified_email(client, "https://api.github.com/user/emails", {})
        assert got == expected
async def _github_sign_in(app_client, monkeypatch, *, user, emails, state):
    """One GitHub callback round-trip: (requested URLs, response, user count before)."""
    calls = _fake_httpx(monkeypatch, user=user, emails=emails)
    before = await _user_count()
    _, resp = await _callback(app_client, monkeypatch, state=state, provider="github")
    return calls, resp, before


async def _account_email(app_client, resp):
    tokens = await app_client.post(
        "/api/v1/auth/oauth/token", json={"code": resp.headers["location"].split("code=")[1]}
    )
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens.json()))
    assert me.status_code == 200, me.text
    return me.json()["email"]


@pytest.fixture
def github_with_emails_url(monkeypatch):
    """github_on, but with emails_url pointed at an operator-chosen URL."""

    def _set(url: str) -> None:
        monkeypatch.setattr(
            settings, "oauth_providers", json.dumps([{**GITHUB, "emails_url": url}])
        )
        monkeypatch.setattr(settings, "auth_allow_registration", True)

    _set(GITHUB["emails_url"])
    yield _set
    monkeypatch.setattr(settings, "oauth_providers", "")
    monkeypatch.setattr(settings, "auth_allow_registration", True)


# A provider that serialises the flag as a non-empty string is not thereby
# claiming verification: only an affirmative value counts, everything else is
# refused so an unverified address is never taken.
async def test_github_refuses_string_false_verified(app_client, github_on, monkeypatch):
    _, resp, before = await _github_sign_in(
        app_client,
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": None},
        emails=[{"email": "octo@example.com", "primary": True, "verified": "false"}],
        state="gsf",
    )
    assert resp.headers["location"].startswith("http://localhost:5173/login?error=sign-in%20failed")
    assert await _user_count() == before


@pytest.mark.parametrize("flag", [True, 1, "1", "true", "TRUE", "True", "yes", "Yes", " true "])
async def test_verified_flag_accepts_affirmative_serialisations(
    app_client, github_on, monkeypatch, flag
):
    _, resp, before = await _github_sign_in(
        app_client,
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": None},
        emails=[{"email": "octo@example.com", "primary": True, "verified": flag}],
        state="gok",
    )
    assert "/oauth/callback?code=" in resp.headers["location"]
    assert await _user_count() == before + 1


@pytest.mark.parametrize("flag", [False, "false", "False", "FALSE", 0, "0", "no", "No", "", None])
async def test_verified_flag_refuses_every_other_value(app_client, github_on, monkeypatch, flag):
    _, resp, before = await _github_sign_in(
        app_client,
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": None},
        emails=[{"email": "octo@example.com", "primary": True, "verified": flag}],
        state="gno",
    )
    assert resp.headers["location"].startswith("http://localhost:5173/login?error=sign-in%20failed")
    assert await _user_count() == before


async def test_verified_flag_refuses_when_key_absent(app_client, github_on, monkeypatch):
    _, resp, before = await _github_sign_in(
        app_client,
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": None},
        emails=[{"email": "octo@example.com", "primary": True}],
        state="gabs",
    )
    assert resp.headers["location"].startswith("http://localhost:5173/login?error=sign-in%20failed")
    assert await _user_count() == before


async def test_github_ignores_string_false_primary(app_client, github_on, monkeypatch):
    _, resp, _ = await _github_sign_in(
        app_client,
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": None},
        emails=[
            {"email": "octo@example.com", "primary": "false", "verified": True},
            {"email": "Alt@Example.com", "primary": True, "verified": True},
        ],
        state="gp",
    )
    assert await _account_email(app_client, resp) == "alt@example.com"


async def test_github_whitespace_profile_email_falls_back_to_emails_endpoint(
    app_client, github_on, monkeypatch
):
    calls, resp, before = await _github_sign_in(
        app_client,
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": "  ", "name": "The Octocat"},
        emails=[{"email": " Octo@Example.com ", "primary": True, "verified": True}],
        state="gws",
    )
    assert "https://api.github.com/user/emails" in calls
    assert "/oauth/callback?code=" in resp.headers["location"]
    assert await _account_email(app_client, resp) == "octo@example.com"
    assert await _user_count() == before + 1


async def test_github_refuses_whitespace_only_email(app_client, github_on, monkeypatch):
    _, resp, before = await _github_sign_in(
        app_client,
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": " "},
        emails=[{"email": "  ", "primary": True, "verified": True}],
        state="gwo",
    )
    assert resp.headers["location"].startswith("http://localhost:5173/login?error=sign-in%20failed")
    assert await _user_count() == before


@pytest.mark.parametrize(
    "url",
    [
        "https://api.github.com.evil.com/user/emails",
        "https://api.github.com@evil.com/user/emails",
    ],
)
async def test_emails_url_off_provider_host_is_refused(
    app_client, github_with_emails_url, monkeypatch, url
):
    github_with_emails_url(url)
    # emails=None raises if /emails is hit at all, so the call list is the proof
    # of whether the bearer token left the process.
    calls, resp, before = await _github_sign_in(
        app_client,
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": None},
        emails=None,
        state="gx",
    )
    assert not [c for c in calls if "evil.com" in c]
    assert resp.headers["location"].startswith("http://localhost:5173/login?error=sign-in%20failed")
    assert await _user_count() == before


async def test_emails_url_on_non_default_port_of_config_host_passes(
    app_client, github_with_emails_url, monkeypatch
):
    # hostname ignores the port, so a provider on :8443 is still its own host.
    github_with_emails_url("https://api.github.com:8443/user/emails")
    calls, resp, before = await _github_sign_in(
        app_client,
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": None},
        emails=[{"email": "octo@example.com", "primary": True, "verified": True}],
        state="gport",
    )
    assert "https://api.github.com:8443/user/emails" in calls
    assert "/oauth/callback?code=" in resp.headers["location"]
    assert await _user_count() == before + 1


async def test_emails_url_of_wrong_type_is_refused(app_client, github_with_emails_url, monkeypatch):
    # A number in the config must not reach urlsplit() as a 500.
    github_with_emails_url(123)
    calls, resp, before = await _github_sign_in(
        app_client,
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": None},
        emails=None,
        state="gtype",
    )
    assert not [c for c in calls if c.endswith("/emails")]
    assert resp.headers["location"].startswith("http://localhost:5173/login?error=sign-in%20failed")
    assert await _user_count() == before


def test_untrusted_emails_urls_reports_bad_config_at_boot(github_with_emails_url):
    github_with_emails_url("https://api.github.com.evil.com/user/emails")
    assert oauth_svc.untrusted_emails_urls() == ["github"]
    github_with_emails_url("https://api.github.com/user/emails")
    assert oauth_svc.untrusted_emails_urls() == []


async def test_discovery_doc_endpoint_anchors_emails_url(app_client, oidc_on, monkeypatch):
    # emails_url sits on userinfo.idp.example, which the config never names; the
    # discovery document does, via its token endpoint.
    oidc_on("https://userinfo.idp.example/user/emails")
    _mock_discovery(
        monkeypatch,
        {
            "authorization_endpoint": "https://idp.example/authorize",
            "token_endpoint": "https://userinfo.idp.example/token",
            "userinfo_endpoint": "https://idp.example/userinfo",
        },
    )
    calls = _fake_httpx(
        monkeypatch,
        user={"id": 4242, "sub": "4242", "email": None},
        emails=[{"email": "octo@example.com", "primary": True, "verified": True}],
    )
    _, resp = await _callback(app_client, monkeypatch, state="o1", provider="oidcidp")
    assert "https://userinfo.idp.example/user/emails" in calls
    assert "/oauth/callback?code=" in resp.headers["location"]


async def test_discovery_doc_anchors_cross_host_userinfo_endpoint(app_client, oidc_on, monkeypatch):
    # Google serves userinfo from openidconnect.googleapis.com and Entra from
    # graph.microsoft.com, hosts their issuer never names: the document comes from
    # the operator's own https config, so the endpoints it states are anchors too.
    oidc_on("")
    _mock_discovery(
        monkeypatch,
        {
            "authorization_endpoint": "https://idp.example/authorize",
            "token_endpoint": "https://idp.example/token",
            "userinfo_endpoint": "https://userinfo.idp.example/userinfo",
        },
    )
    calls = _fake_httpx(
        monkeypatch,
        user={"id": 4242, "sub": "4242", "email": "octo@example.com", "name": "Octo"},
        emails=None,
    )
    _, resp = await _callback(app_client, monkeypatch, state="o2", provider="oidcidp")
    assert "https://userinfo.idp.example/userinfo" in calls
    assert await _account_email(app_client, resp) == "octo@example.com"

async def test_discovery_over_plain_http_is_refused(monkeypatch):
    # A forged document is what could name a third party's endpoints, so one is
    # never fetched over plaintext: no request leaves the process at all.
    calls = _fake_httpx(monkeypatch, user={}, emails=[])
    cfg = oauth_svc.ProviderConfig(
        id="oidcidp",
        display_name="OIDC IdP",
        client_id="cid",
        client_secret="csecret",
        discovery_url="http://idp.example/.well-known/openid-configuration",
    )
    with pytest.raises(oauth_svc.OAuthError, match="must be https"):
        await oauth_svc._discovery(cfg, oauth_svc.TtlCache())
    assert calls == []

async def test_plaintext_token_endpoint_is_refused(monkeypatch):
    # client_secret is posted to the token endpoint, so it is origin-checked like
    # the bearer ones. The config is the trust root, so the host rule cannot bite
    # here; the scheme rule is what refuses a plaintext secret.
    calls = _fake_httpx(monkeypatch, user={}, emails=[])
    provider = oauth_svc.ProviderConfig(
        id="oidcidp",
        display_name="OIDC IdP",
        client_id="cid",
        client_secret="csecret",
        discovery_url="https://idp.example/.well-known/openid-configuration",
    )
    with pytest.raises(oauth_svc.OAuthError, match="token endpoint"):
        await oauth_svc.exchange_code(
            provider,
            {"token_endpoint": "http://idp.example/token"},
            code="c",
            redirect_uri="http://app.test/cb",
        )
    assert calls == []
    # Control: the same endpoint over https is posted to.
    ok = await oauth_svc.exchange_code(
        provider,
        {"token_endpoint": "https://idp.example/token"},
        code="c",
        redirect_uri="http://app.test/cb",
    )
    assert ok["access_token"] == "at" and calls == ["https://idp.example/token"]

async def test_plaintext_userinfo_endpoint_is_refused(app_client, oidc_on, monkeypatch):
    # The bearer never leaves over plaintext either, config-named host or not.
    oidc_on("")
    _mock_discovery(
        monkeypatch,
        {
            "authorization_endpoint": "https://idp.example/authorize",
            "token_endpoint": "https://idp.example/token",
            "userinfo_endpoint": "http://idp.example/userinfo",
        },
    )
    calls = _fake_httpx(monkeypatch, user={"sub": "1", "email": "octo@example.com"}, emails=None)
    before = await _user_count()
    _, resp = await _callback(app_client, monkeypatch, state="o3", provider="oidcidp")
    assert not [c for c in calls if c.startswith("http://")]
    assert resp.headers["location"].startswith("http://localhost:5173/login?error=sign-in%20failed")
    assert await _user_count() == before

def test_boot_check_is_config_only_and_may_be_conservative(oidc_on):
    # The document cannot be fetched at boot, so a doc-anchored emails_url is
    # named there and accepted at the callback; main.py says "may fail".
    oidc_on("https://userinfo.idp.example/user/emails")
    assert oauth_svc.untrusted_emails_urls() == ["oidcidp"]

def test_untrusted_emails_urls_skips_entries_that_cannot_be_selected(monkeypatch):
    # get_provider() matches a raw id against a route string, so a numeric id and
    # a non-dict entry are not providers at all and are not reported as broken.
    monkeypatch.setattr(
        settings,
        "oauth_providers",
        json.dumps(
            [
                {"id": 123, "emails_url": "https://api.github.com.evil.com/user/emails"},
                "not-a-dict",
            ]
        ),
    )
    assert oauth_svc.untrusted_emails_urls() == []


async def test_non_string_provider_email_is_refused(app_client, github_on, monkeypatch):
    _fake_httpx(
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": None},
        emails=[{"email": ["octo@example.com"], "primary": True, "verified": True}],
    )
    before = await _user_count()
    _, resp = await _callback(app_client, monkeypatch, state="g6", provider="github")
    assert resp.headers["location"].startswith("http://localhost:5173/login?error=sign-in%20failed")
    assert await _user_count() == before


async def test_emails_url_plain_http_is_refused(app_client, github_with_emails_url, monkeypatch):
    github_with_emails_url("http://api.github.com/user/emails")
    calls, resp, before = await _github_sign_in(
        app_client,
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": None},
        emails=None,
        state="ghttp",
    )
    assert not [c for c in calls if c.endswith("/emails")]
    assert resp.headers["location"].startswith("http://localhost:5173/login?error=sign-in%20failed")
    assert await _user_count() == before


async def test_github_public_email_skips_emails_endpoint(app_client, github_on, monkeypatch):
    calls = _fake_httpx(
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": "octo@example.com", "name": "The Octocat"},
        emails=None,
    )
    before = await _user_count()
    _, resp = await _callback(app_client, monkeypatch, state="g3", provider="github")
    assert resp.status_code == 302
    assert "/oauth/callback?code=" in resp.headers["location"]
    assert not [c for c in calls if c.endswith("/emails")]
    assert await _user_count() == before + 1


async def test_github_subject_is_numeric_account_id(app_client, github_on, monkeypatch):
    _fake_httpx(
        monkeypatch,
        user={"id": 4242, "login": "octocat", "email": "octo@example.com"},
        emails=None,
    )
    _, first = await _callback(app_client, monkeypatch, state="g4", provider="github")
    assert first.status_code == 302
    # Renamed account: same numeric id, different login and email, same user.
    _fake_httpx(
        monkeypatch,
        user={"id": 4242, "login": "octo-renamed", "email": "renamed@example.com"},
        emails=None,
    )
    before = await _user_count()
    _, second = await _callback(app_client, monkeypatch, state="g5", provider="github")
    assert second.status_code == 302
    assert await _user_count() == before


async def test_oauth_error_redirect_allowlisted(app_client, oauth_on):
    resp = await app_client.get(
        "/api/v1/auth/oauth/testidp/callback?code=x&state=bogus", follow_redirects=False
    )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("http://localhost:5173/login?error=")
