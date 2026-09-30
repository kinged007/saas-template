"""Generic OIDC/OAuth2 login over stdlib + httpx + PyJWT (no new dependency).

One config shape covers every enterprise IdP: OIDC discovery
(discovery_url or issuer) for Google/Microsoft Entra/Okta/GitLab, or
explicit authorize/token/userinfo URLs for non-OIDC providers like GitHub.
Secrets come from env (OAUTH_PROVIDERS JSON); only ids and display names
ever leave the server.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from src.core.cache import TtlCache
from src.settings import settings

logger = logging.getLogger(__name__)

STATE_TTL_HINT = "oauth:state:"
CODE_TTL_HINT = "oauth:code:"

DEFAULT_SCOPES = "openid email profile"


class OAuthError(Exception):
    pass


@dataclass
class ProviderConfig:
    id: str
    display_name: str
    client_id: str
    client_secret: str
    scopes: str = DEFAULT_SCOPES
    discovery_url: str | None = None
    issuer: str | None = None
    authorize_url: str | None = None
    token_url: str | None = None
    userinfo_url: str | None = None
    emails_url: str | None = None
    jwks_uri: str | None = None

    @property
    def label(self) -> str:
        return self.display_name or self.id


def get_provider(provider_id: str) -> ProviderConfig:
    for raw in settings.oauth_provider_list:
        if raw.get("id") == provider_id:
            client_id = str(raw.get("client_id") or "")
            client_secret = str(raw.get("client_secret") or "")
            if not client_id or not client_secret:
                raise OAuthError(f"oauth provider '{provider_id}' is missing client credentials")
            return ProviderConfig(
                id=provider_id,
                display_name=str(raw.get("display_name") or provider_id),
                client_id=client_id,
                client_secret=client_secret,
                scopes=str(raw.get("scopes") or DEFAULT_SCOPES),
                discovery_url=raw.get("discovery_url"),
                issuer=raw.get("issuer"),
                authorize_url=raw.get("authorize_url"),
                token_url=raw.get("token_url"),
                userinfo_url=raw.get("userinfo_url"),
                emails_url=raw.get("emails_url"),
                jwks_uri=raw.get("jwks_uri"),
            )
    raise OAuthError(f"unknown oauth provider '{provider_id}'")


async def _discovery(provider: ProviderConfig, cache: TtlCache) -> dict[str, Any]:
    """OIDC discovery document, cached; explicit URLs skip discovery entirely."""
    if provider.discovery_url is None and provider.issuer is None:
        return {
            "authorization_endpoint": provider.authorize_url,
            "token_endpoint": provider.token_url,
            "userinfo_endpoint": provider.userinfo_url,
            "jwks_uri": provider.jwks_uri,
        }
    url = (
        provider.discovery_url or f"{provider.issuer.rstrip('/')}/.well-known/openid-configuration"
    )
    key = f"oauth:discovery:{provider.id}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            doc = resp.json()
    except Exception as exc:
        raise OAuthError(f"could not load discovery document for '{provider.id}'") from exc
    cache.set(key, doc)
    return doc


def build_authorize_url(
    provider: ProviderConfig, doc: dict[str, Any], cache: TtlCache, redirect_uri: str
) -> str:
    endpoint = doc.get("authorization_endpoint") or provider.authorize_url
    if not endpoint:
        raise OAuthError(f"oauth provider '{provider.id}' has no authorize endpoint")
    state = secrets.token_urlsafe(32)
    cache.set(STATE_TTL_HINT + state, {"provider": provider.id, "redirect_uri": redirect_uri})
    params = httpx.QueryParams(
        {
            "response_type": "code",
            "client_id": provider.client_id,
            "redirect_uri": redirect_uri,
            "scope": provider.scopes,
            "state": state,
        }
    )
    return f"{endpoint}?{params}"


def consume_state(cache: TtlCache, state: str) -> dict[str, Any]:
    entry = cache.get(STATE_TTL_HINT + state)
    if entry is None:
        raise OAuthError("invalid or expired state")
    # Single-use: drop so a replayed callback cannot mint another code.
    cache.delete(STATE_TTL_HINT + state)
    if not isinstance(entry, dict) or not entry.get("provider"):
        raise OAuthError("invalid or expired state")
    return entry


async def exchange_code(
    provider: ProviderConfig,
    doc: dict[str, Any],
    *,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    endpoint = doc.get("token_endpoint") or provider.token_url
    if not endpoint:
        raise OAuthError(f"oauth provider '{provider.id}' has no token endpoint")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": provider.client_id,
                    "client_secret": provider.client_secret,
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        raise OAuthError("code exchange failed") from exc


async def _jwks(
    provider: ProviderConfig, doc: dict[str, Any], cache: TtlCache, refresh: bool = False
) -> dict[str, Any]:
    """The provider's key set, cached next to discovery so a login does not refetch it.

    Fetched over httpx rather than `jwt.PyJWKClient` so the round trip is awaited
    (PyJWKClient fetches with blocking urllib) and covered by the same 10s timeout
    as the module's other IdP calls.
    """
    uri = doc.get("jwks_uri") or provider.jwks_uri
    if not uri:
        raise OAuthError(f"oauth provider '{provider.id}' has no jwks_uri")
    key = f"oauth:jwks:{provider.id}"
    cached = None if refresh else cache.get(key)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(uri)
            resp.raise_for_status()
            keys = resp.json()
        if not isinstance(keys, dict):
            raise ValueError("JWKS response is not a JSON object")
    except Exception as exc:
        raise OAuthError("could not load signing keys") from exc
    cache.set(key, keys)
    return keys


def _signing_key(keys: dict[str, Any], id_token: str) -> jwt.PyJWK | None:
    """The signing key whose kid the token names, or None when the set has no match."""
    kid = jwt.get_unverified_header(id_token).get("kid")
    jwks = jwt.PyJWKSet.from_dict(keys)
    signing = [k for k in jwks.keys if k.public_key_use in (None, "sig")]
    for key in signing:
        if key.key_id == kid:
            return key
    return signing[0] if kid is None and len(signing) == 1 else None


async def claims_from_id_token(
    provider: ProviderConfig, doc: dict[str, Any], id_token: str, cache: TtlCache
) -> dict[str, Any] | None:
    """Verify the id_token signature via JWKS; None when unverifiable."""
    try:
        key = _signing_key(await _jwks(provider, doc, cache), id_token)
        if key is None:
            # A kid the cached set has never seen is the one case a refetch can fix.
            key = _signing_key(await _jwks(provider, doc, cache, refresh=True), id_token)
        if key is None:
            raise OAuthError("no matching signing key")
        return jwt.decode(
            id_token,
            key,
            algorithms=["RS256", "ES256"],
            audience=provider.client_id,
            options={"require": ["exp", "iss", "sub"]},
        )
    except Exception:
        logger.warning("id_token verification failed for provider %s", provider.id)
        return None


async def _verified_email(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> str:
    """Primary verified address from a provider's email list.

    GitHub returns a null email from /user whenever the account keeps its
    address private, and only this endpoint states whether an address is
    verified. The claim is the provider's, not proof of mailbox control.
    """
    resp = await client.get(url, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    entries = (
        [e for e in data if isinstance(e, dict) and e.get("verified") and e.get("email")]
        if isinstance(data, list)
        else []
    )
    chosen = next((e for e in entries if e.get("primary")), None) or next(iter(entries), None)
    return str(chosen["email"]) if chosen else ""


async def fetch_userinfo(
    provider: ProviderConfig, doc: dict[str, Any], access_token: str
) -> dict[str, Any]:
    endpoint = doc.get("userinfo_endpoint") or provider.userinfo_url
    if not endpoint:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = await client.get(endpoint, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                return {}
            if not data.get("email") and provider.emails_url:
                data["email"] = await _verified_email(client, provider.emails_url, headers)
            return data
    except Exception as exc:
        raise OAuthError("could not fetch user info") from exc


def normalize_identity(
    *, provider_id: str, claims: dict[str, Any] | None, userinfo: dict[str, Any]
) -> dict[str, Any]:
    """subject + email + names from id_token claims merged over userinfo.

    Claims win on key collision: the signed id_token is authoritative over
    the bearer-token userinfo response. GitHub (no OIDC) arrives
    claims-less: sub falls back to userinfo id/login.
    """
    merged = {**(userinfo or {}), **(claims or {})}
    subject = str(merged.get("sub") or merged.get("id") or merged.get("login") or "")
    email = merged.get("email") or ""
    if not subject or not email:
        raise OAuthError("provider did not return an email address")
    name = merged.get("name") or ""
    given = merged.get("given_name")
    family = merged.get("family_name")
    if not given and not family and name:
        parts = str(name).strip().split()
        given, family = (parts[0], " ".join(parts[1:])) if len(parts) > 1 else (parts[0], None)
    return {
        "provider": provider_id,
        "subject": subject,
        "email": str(email).lower(),
        "display_name": str(name) if name else None,
        "first_name": str(given) if given else None,
        "last_name": str(family) if family else None,
    }
