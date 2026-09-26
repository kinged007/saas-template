"""Account linking: attach an OAuth identity to a signed-in user, list and
unlink. No network: provider exchanges are monkeypatched like test_oauth.py."""

import json

import pytest
from sqlalchemy import select

import src.api.routes.oauth as oauth_routes
from src.db.session import SessionFactory
from src.models.oauth import OAuthAccount
from src.models.workspace import User
from src.services import oauth as oauth_svc
from src.settings import settings
from tests.conftest import auth_headers, register_user
from tests.test_oauth import PROVIDERS, _mock_oauth

LINK = "/api/v1/auth/oauth"


@pytest.fixture
def oauth_on(monkeypatch):
    monkeypatch.setattr(settings, "oauth_providers", json.dumps(PROVIDERS))
    yield
    monkeypatch.setattr(settings, "oauth_providers", "")


async def _sign_up(client, email: str) -> tuple[dict, str]:
    """Register a password user; return (auth headers, user id)."""
    tokens = await register_user(client, email=email)
    headers = auth_headers(tokens)
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def csrf_headers(headers: dict) -> dict:
    """`require_csrf` guards the link-token mint: an allowed Origin plus the
    X-Requested-With header, which a cross-site form post cannot send."""
    return {
        **headers,
        "Origin": "http://localhost:5173",
        "X-Requested-With": "XMLHttpRequest",
    }


def _seed_state(state: str, *, link_user_id: str | None = None) -> None:
    """Write the state entry /authorize would have written.

    The browser cookie /authorize sets is a separate thing; callers that go on
    to call the callback must also set it on the client (see `_link`)."""
    from src.main import app as fastapi_app

    saved: dict = {"provider": "testidp", "redirect_uri": "http://test/cb"}
    if link_user_id is not None:
        saved["link_user_id"] = link_user_id
    fastapi_app.state.container.cache.set(oauth_svc.STATE_TTL_HINT + state, saved)


async def _link(client, monkeypatch, state: str, *, sub: str, email: str, link_user_id: str) -> str:
    """Drive a full link round-trip and return the one-time code."""
    _mock_oauth(monkeypatch, sub=sub, email=email)
    _seed_state(state, link_user_id=link_user_id)
    client.cookies.set(oauth_routes.STATE_COOKIE, state)
    resp = await client.get(
        f"{LINK}/testidp/callback?code=authcode&state={state}", follow_redirects=False
    )
    assert resp.status_code == 302, resp.text
    return resp.headers["location"].split("code=")[1]


async def _links_for(user_id: str) -> list[OAuthAccount]:
    async with SessionFactory() as s:
        stmt = select(OAuthAccount).where(OAuthAccount.user_id == user_id)
        return list((await s.execute(stmt)).scalars().all())


async def test_link_attaches_identity_and_mints_no_tokens(app_client, oauth_on, monkeypatch):
    headers, user_id = await _sign_up(app_client, "owner@example.com")

    code = await _link(
        app_client,
        monkeypatch,
        state="s1",
        sub="sub-owner",
        email="owner@example.com",
        link_user_id=user_id,
    )
    body = await app_client.post(f"{LINK}/token", json={"code": code})
    assert body.status_code == 200, body.text
    assert body.json() == {"linked": True, "provider": "testidp"}

    listed = await app_client.get(f"{LINK}/identities", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["provider"] == "testidp"
    assert rows[0]["email"] == "owner@example.com"

    stored = await _links_for(user_id)
    assert len(stored) == 1
    assert stored[0].subject == "sub-owner"


async def test_link_creates_no_second_account(app_client, oauth_on, monkeypatch):
    headers, user_id = await _sign_up(app_client, "owner@example.com")
    code = await _link(
        app_client,
        monkeypatch,
        state="s1",
        sub="sub-owner",
        email="totally-other@example.com",
        link_user_id=user_id,
    )
    await app_client.post(f"{LINK}/token", json={"code": code})
    async with SessionFactory() as s:
        users = (await s.execute(select(User))).scalars().all()
    assert [u.email for u in users] == ["owner@example.com"]


async def test_authorize_carries_link_user_id(app_client, oauth_on):
    headers, user_id = await _sign_up(app_client, "owner@example.com")
    mint = await app_client.post(f"{LINK}/identities/link-token", headers=csrf_headers(headers))
    assert mint.status_code == 201, mint.text
    link_token = mint.json()["link_token"]

    from src.main import app as fastapi_app

    resp = await app_client.get(
        f"{LINK}/testidp/authorize?link={link_token}", follow_redirects=False
    )
    assert resp.status_code == 302
    state = resp.headers["location"].split("state=")[1].split("&")[0]
    saved = fastapi_app.state.container.cache.get(oauth_svc.STATE_TTL_HINT + state)
    assert saved["link_user_id"] == user_id
    # Ticket is spent by /authorize, so a replay cannot mint a second state.
    replay = await app_client.get(
        f"{LINK}/testidp/authorize?link={link_token}", follow_redirects=False
    )
    assert "error=invalid%20or%20expired%20link%20token" in replay.headers["location"]


async def test_link_token_requires_authentication(app_client, oauth_on):
    assert (await app_client.get(f"{LINK}/identities")).status_code == 401
    assert (await app_client.post(f"{LINK}/identities/link-token")).status_code == 401


async def test_identity_owned_by_another_user_is_not_stolen(app_client, oauth_on, monkeypatch):
    _, owner_id = await _sign_up(app_client, "first@example.com")
    code = await _link(
        app_client,
        monkeypatch,
        state="s-owner",
        sub="sub-1",
        email="first@example.com",
        link_user_id=owner_id,
    )
    await app_client.post(f"{LINK}/token", json={"code": code})

    _, victim_id = await _sign_up(app_client, "victim@example.com")
    _mock_oauth(monkeypatch, sub="sub-1", email="first@example.com")
    _seed_state("s-steal", link_user_id=victim_id)
    app_client.cookies.set(oauth_routes.STATE_COOKIE, "s-steal")
    resp = await app_client.get(
        f"{LINK}/testidp/callback?code=authcode&state=s-steal", follow_redirects=False
    )
    assert resp.status_code == 302
    assert "code=" not in resp.headers["location"]
    assert "already" in resp.headers["location"]


async def test_unlink_removes_the_link(app_client, oauth_on, monkeypatch):
    headers, user_id = await _sign_up(app_client, "pw@example.com")
    code = await _link(
        app_client,
        monkeypatch,
        state="s1",
        sub="sub-pw",
        email="pw@example.com",
        link_user_id=user_id,
    )
    await app_client.post(f"{LINK}/token", json={"code": code})

    link_id = (await _links_for(user_id))[0].id
    resp = await app_client.delete(f"{LINK}/identities/{link_id}", headers=headers)
    assert resp.status_code == 204, resp.text
    assert await _links_for(user_id) == []


async def test_unlink_refused_for_sso_only_account(app_client, oauth_on, monkeypatch):
    """The last identity cannot be removed when no password is left to fall back on."""
    headers, user_id = await _sign_up(app_client, "ssoonly@example.com")
    code = await _link(
        app_client,
        monkeypatch,
        state="s1",
        sub="sub-sso",
        email="ssoonly@example.com",
        link_user_id=user_id,
    )
    await app_client.post(f"{LINK}/token", json={"code": code})

    async with SessionFactory() as s:
        stmt = select(User).where(User.email == "ssoonly@example.com")
        row = (await s.execute(stmt)).scalar_one()
        row.password_hash = None
        await s.commit()

    link_id = (await _links_for(user_id))[0].id
    resp = await app_client.delete(f"{LINK}/identities/{link_id}", headers=headers)
    assert resp.status_code == 400, resp.text
    assert "password" in resp.json()["detail"].lower()
    assert len(await _links_for(user_id)) == 1


async def test_unlink_allowed_when_another_identity_remains(app_client, oauth_on, monkeypatch):
    headers, user_id = await _sign_up(app_client, "two@example.com")
    for state, sub in (("s1", "sub-a"), ("s2", "sub-b")):
        code = await _link(
            app_client,
            monkeypatch,
            state=state,
            sub=sub,
            email="two@example.com",
            link_user_id=user_id,
        )
        await app_client.post(f"{LINK}/token", json={"code": code})
    assert len(await _links_for(user_id)) == 2

    async with SessionFactory() as s:
        stmt = select(User).where(User.email == "two@example.com")
        row = (await s.execute(stmt)).scalar_one()
        row.password_hash = None
        await s.commit()

    first = (await _links_for(user_id))[0].id
    unlink = await app_client.delete(f"{LINK}/identities/{first}", headers=headers)
    assert unlink.status_code == 204
    assert len(await _links_for(user_id)) == 1


async def test_cannot_unlink_another_users_identity(app_client, oauth_on):
    headers, _ = await _sign_up(app_client, "mine@example.com")
    async with SessionFactory() as s:
        stranger = OAuthAccount(
            user_id="00000000-0000-0000-0000-000000000000", provider="x", subject="y"
        )
        s.add(stranger)
        await s.commit()
        stranger_id = stranger.id
    resp = await app_client.delete(f"{LINK}/identities/{stranger_id}", headers=headers)
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "linked account not found"


async def test_callback_rejects_state_from_another_browser(app_client, oauth_on, monkeypatch):
    """A state the browser never received is login CSRF: the attacker opens
    their own callback URL in the victim's browser and signs it in as them."""
    headers, user_id = await _sign_up(app_client, "victim@example.com")
    _mock_oauth(monkeypatch, sub="sub-attacker", email="attacker@example.com")
    _seed_state("s-csrf", link_user_id=user_id)
    # Deliberately no client.cookies.set: this browser never got the state.
    resp = await app_client.get(
        f"{LINK}/testidp/callback?code=authcode&state=s-csrf", follow_redirects=False
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
    assert "code=" not in resp.headers["location"]


async def test_link_token_mint_requires_csrf_header(app_client, oauth_on):
    """Refresh-cookie auth sends no CSRF header, so a cross-site POST could mint
    a link ticket and commit the signed-in user to the attacker's IdP account."""
    headers, _ = await _sign_up(app_client, "csrf-victim@example.com")
    resp = await app_client.post(f"{LINK}/identities/link-token", headers=headers)
    assert resp.status_code == 403, resp.text
    assert "link_token" not in resp.text


async def test_link_token_mint_rejects_foreign_origin(app_client, oauth_on):
    headers, _ = await _sign_up(app_client, "origin-victim@example.com")
    resp = await app_client.post(
        f"{LINK}/identities/link-token",
        headers={
            **headers,
            "Origin": "https://evil.example",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    assert resp.status_code == 403, resp.text


async def test_delete_account_removes_oauth_links(app_client, oauth_on, monkeypatch):
    """The (provider, subject) row must go with the user, or the unique
    constraint locks that IdP out of the address forever."""
    headers, user_id = await _sign_up(app_client, "gone@example.com")
    code = await _link(
        app_client,
        monkeypatch,
        state="s1",
        sub="sub-gone",
        email="gone@example.com",
        link_user_id=user_id,
    )
    await app_client.post(f"{LINK}/token", json={"code": code})
    assert len(await _links_for(user_id)) == 1

    resp = await app_client.request(
        "DELETE",
        "/api/v1/me",
        headers=headers,
        json={"confirm": "DELETE", "password": "Password123!"},
    )
    assert resp.status_code == 204, resp.text
    assert await _links_for(user_id) == []
