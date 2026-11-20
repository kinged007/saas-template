"""Generic OIDC/OAuth2 login over stdlib + httpx + PyJWT (no new dependency).

One config shape covers every enterprise IdP: OIDC discovery
(discovery_url or issuer) for Google/Microsoft Entra/Okta/GitLab, or
explicit authorize/token/userinfo URLs for non-OIDC providers like GitHub.
The authorization-code flow uses PKCE (S256) on every provider; the verifier
lives in the server-side state entry, never in the browser. Unconditional on
purpose: RFC 6749 §3.1 obliges a compliant authorization server to ignore
unknown authorize params, so a per-provider toggle only helps an AS that
rejects them. Secrets come from env
(OAUTH_PROVIDERS JSON); only ids and display names ever leave the server.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt

from src.core.cache import SingleFlight, TtlCache
from src.settings import settings

logger = logging.getLogger(__name__)

STATE_TTL_HINT = "oauth:state:"
CODE_TTL_HINT = "oauth:code:"

DEFAULT_SCOPES = "openid email profile"

# A plain-http IdP on loopback cannot offer https, and loopback is not routable
# off the machine, so it is the one scheme exception the origin guards allow.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Providers serialise the boolean flags on an email entry as a real JSON
# boolean, as a string, or as a number, so they are read against an allowlist:
# anything else is refused rather than read by truthiness, where "false" and
# "no" would both read as verified.
_AFFIRMATIVE_FLAGS = frozenset({"true", "1", "yes"})


def _affirmative(value: Any) -> bool:
    return str(value).strip().lower() in _AFFIRMATIVE_FLAGS


def _clean_email(value: Any) -> str:
    """A provider-supplied address, stripped; empty unless it is a string.

    A non-string is refused rather than coerced, so a list address cannot
    become the account email as "['a@b.c']".
    """
    return value.strip() if isinstance(value, str) else ""


# One shared in-flight fetch per cache key, so a burst of callers that miss the
# cache (or bypass it for a refresh) costs the IdP one request, not one per caller.
_inflight = SingleFlight()


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


def _provider_from(raw: dict[str, Any], provider_id: str) -> ProviderConfig:
    """One OAUTH_PROVIDERS entry as a config object, every URL field a str."""
    return ProviderConfig(
        id=provider_id,
        display_name=str(raw.get("display_name") or provider_id),
        client_id=str(raw.get("client_id") or ""),
        client_secret=str(raw.get("client_secret") or ""),
        scopes=str(raw.get("scopes") or DEFAULT_SCOPES),
        discovery_url=str(raw.get("discovery_url") or "") or None,
        issuer=str(raw.get("issuer") or "") or None,
        authorize_url=str(raw.get("authorize_url") or "") or None,
        token_url=str(raw.get("token_url") or "") or None,
        userinfo_url=str(raw.get("userinfo_url") or "") or None,
        emails_url=str(raw.get("emails_url") or "").strip() or None,
        jwks_uri=str(raw.get("jwks_uri") or "") or None,
    )


def get_provider(provider_id: str) -> ProviderConfig:
    for raw in settings.oauth_provider_list:
        if not isinstance(raw, dict):
            continue
        if raw.get("id") == provider_id:
            provider = _provider_from(raw, provider_id)
            if not provider.client_id or not provider.client_secret:
                raise OAuthError(f"oauth provider '{provider_id}' is missing client credentials")
            return provider
    raise OAuthError(f"unknown oauth provider '{provider_id}'")


def untrusted_emails_urls() -> list[str]:
    """Provider ids whose emails_url the origin guard would refuse.

    Called at boot so a config that cannot sign in is reported at deploy time
    rather than at the first callback. The check is config-only - no discovery
    document is fetched here - so a provider whose emails_url is anchored only
    by the document is reported even though the callback accepts it.
    """
    untrusted: list[str] = []
    for raw in settings.oauth_provider_list:
        # An entry that is not a dict, or whose id is not a string, can never be
        # selected by get_provider(), so it is not a provider to report on either.
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            continue
        provider = _provider_from(raw, raw["id"])
        if provider.emails_url and not _endpoint_trusted(provider, {}, provider.emails_url):
            untrusted.append(provider.id)
    return untrusted


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
    # The document names every endpoint a secret is later sent to, so it is
    # fetched over https only: a plaintext one is an on-path attacker's to write.
    if not _origin_ok(url):
        raise OAuthError(f"discovery_url for '{provider.id}' must be https")
    key = f"oauth:discovery:{provider.id}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    async def fetch() -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                doc = resp.json()
        except Exception as exc:
            raise OAuthError(
                f"could not load discovery document for '{provider.id}': {_failure_detail(exc)}"
            ) from exc
        if not isinstance(doc, dict):
            raise OAuthError(f"discovery document for '{provider.id}' is not an object")
        cache.set(key, doc)
        return doc

    return await _inflight.run(key, fetch)


def _pkce_pair() -> tuple[str, str]:
    """RFC 7636 verifier + its S256 challenge; token_urlsafe(64) is 86
    unreserved characters, inside the 43..128 the RFC allows."""
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def build_authorize_url(
    provider: ProviderConfig, doc: dict[str, Any], cache: TtlCache, redirect_uri: str
) -> str:
    endpoint = doc.get("authorization_endpoint") or provider.authorize_url
    if not endpoint:
        raise OAuthError(f"oauth provider '{provider.id}' has no authorize endpoint")
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    cache.set(
        STATE_TTL_HINT + state,
        {"provider": provider.id, "redirect_uri": redirect_uri, "code_verifier": verifier},
    )
    params = httpx.QueryParams(
        {
            "response_type": "code",
            "client_id": provider.client_id,
            "redirect_uri": redirect_uri,
            "scope": provider.scopes,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{endpoint}?{params}"


def consume_state(cache: TtlCache, state: str) -> dict[str, Any]:
    entry = cache.get(STATE_TTL_HINT + state)
    if entry is None:
        raise OAuthError("invalid or expired state")
    # Single-use: drop so a replayed callback cannot mint another code.
    cache.delete(STATE_TTL_HINT + state)
    if not isinstance(entry, dict) or not entry.get("provider") or not entry.get("code_verifier"):
        raise OAuthError("invalid or expired state")
    return entry


async def exchange_code(
    provider: ProviderConfig,
    doc: dict[str, Any],
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any]:
    endpoint = doc.get("token_endpoint") or provider.token_url
    if not endpoint:
        raise OAuthError(f"oauth provider '{provider.id}' has no token endpoint")
    # client_secret is posted here, so the token endpoint gets the same origin
    # check as the bearer-bearing ones, before the client is built.
    if not _endpoint_trusted(provider, doc, endpoint):
        raise OAuthError(
            f"token endpoint for '{provider.id}' is not https on a host the provider names"
        )

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
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            tokens = resp.json()
    except Exception as exc:
        # The body names the cause the status cannot ("invalid_grant" vs. a
        # rejected code_verifier); log-only, the redirect detail stays
        # allowlisted. CR and LF are flattened so a provider cannot forge lines.
        body = getattr(getattr(exc, "response", None), "text", "")
        if body:
            logger.warning(
                "oauth token endpoint error body provider=%s: %s",
                provider.id,
                _single_line(body),
            )
        raise OAuthError(f"code exchange failed: {_failure_detail(exc)}") from exc
    # The callback reads id_token and access_token off the result and catches
    # only OAuthError, so a list, string or null body has to fail here: its
    # AttributeError would escape as a 500.
    if not isinstance(tokens, dict):
        raise OAuthError(f"token response for '{provider.id}' is not an object")
    return tokens


async def _jwks(
    provider: ProviderConfig, doc: dict[str, Any], cache: TtlCache, refresh: bool = False
) -> dict[str, Any]:
    """The provider's key set, cached next to discovery so a login does not refetch it.

    Fetched over httpx rather than `jwt.PyJWKClient` so the round trip is awaited
    (PyJWKClient fetches with blocking urllib) and covered by the same 10s timeout
    as the module's other IdP calls.

    `refresh=True` skips only the cache read, so a kid the provider does not
    publish still costs one extra IdP round trip per login that meets it.
    Concurrent misses share a single in-flight fetch; a sequential miss after a
    completed fetch pays its own request, because a failed or unusable set is
    never cached (#1024). Bounding the sequential case needs a fetch timestamp
    on the cached document; the cost is kept because the path requires a
    completed code exchange.
    """
    uri = doc.get("jwks_uri") or provider.jwks_uri
    # The non-string case is refused here rather than left to httpx, whose TypeError
    # does not say which provider published it.
    if not isinstance(uri, str) or not uri:
        raise OAuthError(f"oauth provider '{provider.id}' has no usable jwks_uri")
    key = f"oauth:jwks:{provider.id}"
    cached = None if refresh else cache.get(key)
    if cached is not None:
        return cached

    async def fetch() -> dict[str, Any]:
        try:
            # `PyJWKClient` fetched through urllib, which follows redirects; httpx does not
            # follow them by default.
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(uri)
                resp.raise_for_status()
                keys = resp.json()
            # Parsed and checked before it is cached: a body that is not an object, or a
            # set with no key a token could verify against, would otherwise sit in the
            # cache for its whole TTL and cost a refetch on every login that meets it.
            # Both gates raise OAuthError, which the re-raise below passes through with
            # its reason intact; anything else raised here is flattened by
            # `_failure_detail` to "HTTP <status>" or a bare type name, which is why
            # `_signing_candidates` has to stay inside the try.
            if not isinstance(keys, dict):
                raise OAuthError(f"key set for '{provider.id}' is not an object")
            if not _signing_candidates(keys):
                raise OAuthError(f"no key published for signing by '{provider.id}'")
        except OAuthError:
            raise
        except Exception as exc:
            raise OAuthError(f"could not load signing keys: {_failure_detail(exc)}") from exc
        cache.set(key, keys)
        return keys

    return await _inflight.run(key, fetch)


def _signing_candidates(jwks_doc: dict[str, Any]) -> list[jwt.PyJWK]:
    """The published keys a token could be verified against.

    Mirrors `jwt.PyJWKClient.get_signing_key`: only keys published for signing that
    carry a kid are candidates.
    """
    return [
        k
        for k in jwt.PyJWKSet.from_dict(jwks_doc).keys
        if k.public_key_use in (None, "sig") and k.key_id
    ]


def _signing_key(jwks_doc: dict[str, Any], id_token: str) -> jwt.PyJWK | None:
    """The signing key whose kid the token names, or None when the set has no match.

    A token without a kid is refused rather than verified against the sole published key.
    """
    kid = jwt.get_unverified_header(id_token).get("kid")
    return next((k for k in _signing_candidates(jwks_doc) if k.key_id == kid), None)


async def claims_from_id_token(
    provider: ProviderConfig, doc: dict[str, Any], id_token: str, cache: TtlCache
) -> dict[str, Any] | None:
    """Verify the id_token signature via JWKS; None when unverifiable."""
    # The document's issuer is what the IdP itself states, so it wins over the
    # configured one; the config covers providers that skip discovery.
    issuer = doc.get("issuer") or provider.issuer
    if not issuer:
        # Nothing to compare `iss` against, so only its presence is enforced.
        logger.warning("no issuer configured for provider %s; id_token iss not pinned", provider.id)
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
            issuer=issuer,
            options={"require": ["exp", "iss", "sub"]},
        )
    except Exception as exc:
        # The message can echo token-supplied header data (an unknown `crit`
        # extension echoes its name), so it is flattened like the body above.
        logger.warning(
            "id_token verification failed for provider %s: %s",
            provider.id,
            _single_line(exc),
            exc_info=logger.isEnabledFor(logging.DEBUG),
        )
        return None


async def _verified_email(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> str:
    """Primary verified address from a provider's email list.

    GitHub returns a null email from /user whenever the account keeps its
    address private, and only this endpoint states whether an address is
    verified. The claim is the provider's, not proof of mailbox control, so an
    entry is taken only when its `verified` flag reads as affirmative and its
    address is present once stripped. Both flags go through the same allowlist,
    so "false" is not a claim of verification on either.
    """
    resp = await client.get(url, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    entries = (
        [
            e
            for e in data
            if isinstance(e, dict)
            and _affirmative(e.get("verified"))
            and _clean_email(e.get("email"))
        ]
        if isinstance(data, list)
        else []
    )
    # No primary flag: fall back to the provider's list order, so the winner
    # is deterministic only while that ordering is stable.
    chosen = next((e for e in entries if _affirmative(e.get("primary"))), None) or next(
        iter(entries), None
    )
    return _clean_email(chosen.get("email")) if chosen else ""


def _url_host_scheme(url: Any) -> tuple[str, str]:
    """Lower-cased (hostname, scheme) of a URL, or ("", "") when unusable."""
    if not isinstance(url, str) or not url:
        return "", ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "", ""
    return (parts.hostname or "").lower(), parts.scheme.lower()


def _origin_ok(url: Any) -> bool:
    """https, except plain http on loopback: a local IdP cannot offer https and
    loopback is not routable off the machine."""
    host, scheme = _url_host_scheme(url)
    return bool(host) and (scheme == "https" or (scheme == "http" and host in _LOOPBACK_HOSTS))


def _anchor_hosts(provider: ProviderConfig, doc: dict[str, Any]) -> set[str]:
    """Hosts named by the provider config, plus the ones in `doc`.

    authorize_url and the document's authorization_endpoint are excluded on
    purpose: they carry no secret, and an attacker-chosen authorize host would
    make itself the anchor.
    """
    anchors = (
        provider.issuer,
        provider.discovery_url,
        provider.token_url,
        provider.userinfo_url,
        provider.jwks_uri,
        doc.get("token_endpoint"),
        doc.get("userinfo_endpoint"),
        doc.get("jwks_uri"),
    )
    return {_url_host_scheme(a)[0] for a in anchors} - {""}


def _endpoint_trusted(provider: ProviderConfig, doc: dict[str, Any], url: Any) -> bool:
    """Whether a secret-bearing request may go to `url`.

    One rule for every destination (userinfo, token, emails): https on a host
    the operator's config or its discovery document names. The document counts
    because `_discovery` accepts it over https only, so it is as trustworthy as
    the config it came from - which is what lets a cross-host IdP pass (Google
    serves userinfo from openidconnect.googleapis.com, Entra from
    graph.microsoft.com) and what a forged document would have to defeat.
    """
    return _origin_ok(url) and _url_host_scheme(url)[0] in _anchor_hosts(provider, doc)


_CC_CONTROLS = "".join(map(chr, [*range(0x20), *range(0x7F, 0xA0)]))
_CC_TO_SPACE = str.maketrans(_CC_CONTROLS, " " * len(_CC_CONTROLS))


def _single_line(text: object, limit: int = 200) -> str:
    """Flatten every Cc control char to a space, then truncate: no log forging, no ANSI escapes."""
    return str(text).translate(_CC_TO_SPACE)[:limit]


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
    # Both bearer destinations are checked before the client is built: a refusal
    # raises its own OAuthError instead of being re-wrapped by the narrowed try
    # below, and the access token never leaves the process.
    if not _endpoint_trusted(provider, doc, endpoint):
        raise OAuthError(
            f"userinfo endpoint for '{provider.id}' is not https on a host the provider names"
        )
    if provider.emails_url and not _endpoint_trusted(provider, doc, provider.emails_url):
        raise OAuthError(
            f"emails_url for '{provider.id}' is not https on a host the provider names"
        )
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
        if not _clean_email(data.get("email")) and provider.emails_url:
            try:
                data["email"] = await _verified_email(client, provider.emails_url, headers)
            except Exception as exc:
                # Branch on the status itself: the rendered detail is wording,
                # and rewording it must not silence the hint below.
                status = getattr(getattr(exc, "response", None), "status_code", None)
                detail = _failure_detail(exc)
                # GitHub answers 404 on /user/emails when the token lacks the
                # email scope: a config fix, so name the scopes to compare.
                if status == 404:
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
    email = _clean_email(merged.get("email"))
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
        "email": email.lower(),
        "display_name": str(name) if name else None,
        "first_name": str(given) if given else None,
        "last_name": str(family) if family else None,
    }
