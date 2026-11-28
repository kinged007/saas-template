"""POST /auth/sign-in/method: email domain to OAuth provider routing."""

import json

import pytest
from pydantic import ValidationError

from src.settings import Settings, settings

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


async def _method(client, email):
    resp = await client.post("/api/v1/auth/sign-in/method", json={"email": email})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_unmapped_domain_returns_no_provider(app_client):
    assert (await _method(app_client, "someone@example.com")) == {"provider": None}


async def test_mapped_domain_returns_provider_without_an_account(app_client, monkeypatch):
    """No user row is consulted: a mapped inbox answers even when nobody
    registered it, so the answer cannot tell whether an account exists."""
    monkeypatch.setattr(settings, "oauth_providers", json.dumps(PROVIDERS))
    monkeypatch.setattr(settings, "sign_in_domains", "corp.example:testidp")
    assert (await _method(app_client, "newhire@corp.example")) == {"provider": "testidp"}
    assert (await _method(app_client, "NEWHIRE@CORP.EXAMPLE")) == {"provider": "testidp"}


async def test_mapped_but_unconfigured_provider_returns_none(app_client, monkeypatch):
    monkeypatch.setattr(settings, "oauth_providers", json.dumps(PROVIDERS))
    monkeypatch.setattr(settings, "sign_in_domains", "corp.example:ghost")
    assert (await _method(app_client, "newhire@corp.example")) == {"provider": None}


async def test_invalid_email_is_rejected(app_client):
    resp = await app_client.post("/api/v1/auth/sign-in/method", json={"email": "not-an-email"})
    assert resp.status_code == 422


async def test_lookup_spends_ip_budget(app_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 2)
    for _ in range(2):
        assert (
            await app_client.post("/api/v1/auth/sign-in/method", json={"email": "a@example.com"})
        ).status_code == 200
    capped = await app_client.post("/api/v1/auth/sign-in/method", json={"email": "a@example.com"})
    assert capped.status_code == 429, capped.text
    assert "Retry-After" in capped.headers


def test_domain_map_validation():
    assert Settings(sign_in_domains="a.com:x,b.com:y").sign_in_domain_map == {
        "a.com": "x",
        "b.com": "y",
    }
    assert Settings(sign_in_domains="").sign_in_domain_map == {}
    with pytest.raises(ValidationError):
        Settings(sign_in_domains="not-a-pair")
    with pytest.raises(ValidationError):
        Settings(sign_in_domains="user@a.com:x")
