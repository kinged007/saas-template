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


def _jwks_client(provider: ProviderConfig, doc: dict[str, Any]) -> jwt.PyJWKClient | None:
    uri = doc.get("jwks_uri") or provider.jwks_uri
    if not uri:
        return None
    return jwt.PyJWKClient(uri)


def claims_from_id_token(
    provider: ProviderConfig, doc: dict[str, Any], id_token: str
) -> dict[str, Any] | None:
    """Verify the id_token signature via JWKS; None when unverifiable."""
    client = _jwks_client(provider, doc)
    if client is None:
        return None
    # The document's issuer is what the IdP itself states, so it wins over the
    # configured one; the config covers providers that skip discovery.
    issuer = doc.get("issuer") or provider.issuer
    if not issuer:
        # Nothing to compare `iss` against, so only its presence is enforced.
        logger.warning("no issuer configured for provider %s; id_token iss not pinned", provider.id)
    try:
        key = client.get_signing_key_from_jwt(id_token).key
        return jwt.decode(
            id_token,
            key,
            algorithms=["RS256", "ES256"],
            audience=provider.client_id,
            issuer=issuer,
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


def _failure_detail(exc: Exception) -> str:
    """HTTP status when the provider answered, else the exception type."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else type(exc).__name__


async def fetch_userinfo(
    provider: ProviderConfig, doc: dict[str, Any], access_token: str
) -> dict[str, Any]:
    endpoint = doc.get("userinfo_endpoint") or provider.userinfo_url
    if not endpoint:
        return {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            resp = await client.get(endpoint, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise OAuthError(
                f"could not fetch user info for '{provider.id}' from {endpoint}: "
                f"{_failure_detail(exc)}"
            ) from exc
        if not isinstance(data, dict):
            return {}
        if not data.get("email") and provider.emails_url:
            try:
                data["email"] = await _verified_email(client, provider.emails_url, headers)
            except Exception as exc:
                detail = _failure_detail(exc)
                # GitHub answers 404 on /user/emails when the token lacks the
                # email scope: a config fix, so name the scopes to compare.
                if detail == "HTTP 404":
                    detail = (
                        f"HTTP 404, token likely lacks an email scope (asked: {provider.scopes})"
                    )
                raise OAuthError(
                    f"could not fetch verified email for '{provider.id}' from "
                    f"{provider.emails_url}: {detail}"
                ) from exc
        return data


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
