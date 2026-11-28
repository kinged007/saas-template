"""Real-provider coverage for the OIDC path.

The pre-existing OAuth tests monkeypatch `_discovery`, `exchange_code` and
`fetch_userinfo` at the service-module boundary, so none of them ever run. This
file drives them for real against an in-process IdP — a `ThreadingHTTPServer`
on `127.0.0.1:0` serving a discovery document, a JWKS, a token endpoint
and a userinfo endpoint. No network egress, no mocked seams, no new dependency
(`pyjwt`, `cryptography` and `httpx` are already runtime deps).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import socket
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from src.core.cache import TtlCache
from src.services.oauth import (
    STATE_TTL_HINT,
    OAuthError,
    ProviderConfig,
    _discovery,
    _jwks,
    _single_line,
    build_authorize_url,
    claims_from_id_token,
    consume_state,
    exchange_code,
    fetch_userinfo,
    get_provider,
)
from src.settings import settings

CLIENT_ID = "cid"
CLIENT_SECRET = "csecret"
KID = "stub-key-1"
EC_KID = "stub-ec-1"
ROTATED_KID = "stub-key-2"
REDIRECT_URI = "http://localhost:8000/api/v1/auth/oauth/stub/callback"
# Distinguishes "a test did not ask for a broken document" from a `null` one.
UNSET = object()


def _jwk(
    key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey, kid: str | None, alg: str
) -> dict[str, Any]:
    # Mirrors the allow-list in src/services/oauth.py; not imported so drift fails loudly.
    algo = {"RS256": jwt.algorithms.RSAAlgorithm, "ES256": jwt.algorithms.ECAlgorithm}[alg]
    pub = json.loads(algo.to_jwk(key.public_key()))
    # A kid of None omits the member, as a provider that assigns no kid would.
    return {**pub, **({"kid": kid} if kid else {}), "use": "sig", "alg": alg}


def test_jwk_rejects_unknown_algorithm(idp):
    """An alg outside the map raises here, at the call site, rather than publishing a key
    labelled with an algorithm it was not built for."""
    with pytest.raises(KeyError, match="PS256"):
        _jwk(idp.signing_key, "kid-x", "PS256")


class _StubIdP:
    """A real HTTP server speaking just enough OIDC to drive the client code.

    Records what it was asked for (`hits`, `token_forms`, `auth_headers`) so the
    tests can assert on the request, not only on the response.
    """

    def __init__(self) -> None:
        self.signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.ec_key = ec.generate_private_key(ec.SECP256R1())
        self.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other_ec_key = ec.generate_private_key(ec.SECP256R1())
        self.hits: list[str] = []
        self.token_forms: list[dict[str, list[str]]] = []
        self.auth_headers: list[str] = []
        # Published key set, mutable so a test can rotate it mid-cache. Both key
        # families are published, so a kid match that ignores the key type is
        # rejected by the kid↔key-type binding rather than by an absent kid.
        self.published: list[tuple[Any, str | None, str]] = [
            (self.signing_key, KID, "RS256"),
            (self.ec_key, EC_KID, "ES256"),
        ]
        # Set by a test to make /jwks-broken answer with an unusable set, and
        # UNSET once the set is usable again, so a JSON `null` set is expressible.
        self.broken_jwks: Any = UNSET
        # Set by a test to make /jwks answer with a body no key set can be read from.
        self.garbage_jwks = False
        self.undecodable_jwks = False
        self.truncated_jwks = False
        # Set by a test to make the well-known document answer with `broken_doc`
        # instead of an object, which a provider should never publish.
        self.broken_doc: Any = UNSET
        # Set by a test to answer the good-code token request with something other
        # than a token object, which a provider should never publish.
        self.broken_tokens: Any = UNSET
        # Set by a test to answer the bad-code token request with raw text of its
        # own, so it can carry bytes json.dumps would escape.
        self.token_error_body: str | None = None
        self.jwks_delay = 0.0
        self.discovery_delay = 0.0
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    @property
    def base(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def doc(self) -> dict[str, str]:
        return {
            "issuer": self.base,
            "authorization_endpoint": f"{self.base}/authorize",
            "token_endpoint": f"{self.base}/token",
            "userinfo_endpoint": f"{self.base}/userinfo",
            "jwks_uri": f"{self.base}/jwks",
        }

    def mint(
        self,
        *,
        kid: str | None = KID,
        key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | None = None,
        alg: str = "RS256",
        drop: tuple[str, ...] = (),
        extra_headers: dict[str, Any] | None = None,
        **claims: Any,
    ) -> str:
        """A signed id_token; every claim is overridable so tests can break one at a time.

        `kid=None` omits the JWT header. `drop` pops claims outright: `**claims`
        can only override, never remove, so `sub=None` would still satisfy presence.
        """
        now = int(time.time())
        payload = {
            "iss": self.base,
            "sub": "sub-1",
            "aud": CLIENT_ID,
            "email": "user@example.com",
            "iat": now,
            "exp": now + 300,
            **claims,
        }
        for name in drop:
            payload.pop(name, None)
        headers = {"kid": kid} if kid is not None else {}
        headers.update(extra_headers or {})
        if alg == "none":
            return jwt.encode(payload, key="", algorithm="none", headers=headers)
        return jwt.encode(payload, key or self.signing_key, algorithm=alg, headers=headers)

    def published_jwks(self) -> dict[str, Any]:
        return {"keys": [_jwk(*p) for p in self.published]}

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                pass  # keep the access log out of the test output

            def _send_raw(self, code: int, body: bytes, declared: int | None = None) -> None:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body) if declared is None else declared))
                self.end_headers()
                self.wfile.write(body)

            # `raw` sends text verbatim; without it the payload is JSON, so a bare
            # str stays a JSON string rather than becoming an unparseable body.
            def _send(self, code: int, payload: Any, raw: str | None = None) -> None:
                body = raw.encode() if raw is not None else json.dumps(payload).encode()
                self._send_raw(code, body)

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                stub.hits.append(self.path)
                if self.path.startswith("/.well-known/openid-configuration-broken"):
                    self._send(200, stub.doc if stub.broken_doc is UNSET else stub.broken_doc)
                elif self.path.startswith("/.well-known/openid-configuration-500"):
                    self._send(500, {"error": "idp_down"})
                elif self.path.startswith("/.well-known/openid-configuration-text"):
                    self._send(200, None, raw="this is not json")
                elif self.path.startswith("/.well-known/openid-configuration"):
                    if stub.discovery_delay:
                        time.sleep(stub.discovery_delay)
                    self._send(200, stub.doc)
                elif self.path == "/jwks":
                    if stub.jwks_delay:
                        time.sleep(stub.jwks_delay)
                    if stub.garbage_jwks:
                        # What a proxy or a captive portal in front of the IdP answers.
                        self._send_raw(200, b"<html>502 Bad Gateway</html>")
                    elif stub.undecodable_jwks:
                        # The right byte count, not decodable as UTF-8.
                        self._send_raw(200, b'{"keys":[{"n":"\xff\xfe"}]}')
                    elif stub.truncated_jwks:
                        # A Content-Length the body never fills, as a proxy cutting the
                        # response off mid-stream does.
                        self._send_raw(200, b'{"keys":[{"kid":"stub-key-1"}]}', declared=4096)
                    else:
                        self._send(200, stub.published_jwks())
                elif self.path == "/jwks-redirect":
                    self.send_response(302)
                    self.send_header("Location", f"{stub.base}/jwks")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif self.path == "/jwks-broken":
                    # Answers with `broken_jwks` while a test holds one, so the IdP can
                    # be made to publish an unusable set and then repair itself.
                    body = stub.published_jwks() if stub.broken_jwks is UNSET else stub.broken_jwks
                    self._send(200, body)
                elif self.path == "/userinfo" or self.path.startswith("/userinfo?"):
                    stub.auth_headers.append(self.headers.get("Authorization", ""))
                    mode = parse_qs(urlsplit(self.path).query).get("mode")
                    if mode == ["500"]:
                        self._send(500, {"error": "idp_down"})
                    elif mode == ["array"]:
                        self._send(200, ["not", "a", "dict"])
                    else:
                        self._send(
                            200,
                            {
                                "sub": "sub-1",
                                "email": "user@example.com",
                                "name": "Stub User",
                            },
                        )
                else:
                    self._send(404, {"error": "not_found"})

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                stub.hits.append(self.path)
                length = int(self.headers.get("Content-Length", 0))
                form = parse_qs(self.rfile.read(length).decode())
                stub.token_forms.append(form)
                if form.get("code", [""])[0] == "bad-code":
                    self._send(400, {"error": "invalid_grant"}, stub.token_error_body)
                else:
                    self._send(
                        200,
                        {
                            "access_token": "at-stub",
                            "token_type": "Bearer",
                            "id_token": stub.mint(),
                        }
                        if stub.broken_tokens is UNSET
                        else stub.broken_tokens,
                    )

        return Handler


@pytest.fixture(scope="module")
def idp():
    stub = _StubIdP()
    yield stub
    stub.close()


@pytest.fixture(autouse=True)
async def _clean_db():
    """No-op override of the autouse fixture in conftest.

    These tests never touch the database, and each default unlink/recreate cycle
    churns the SQLite file the whole suite shares (#319). Skipping it here keeps the
    pointless teardowns out of every full run.

    This is a workaround for #319, not a fix — skipping the churn is also what
    keeps tests/test_jobs_atomicity_battle.py green. Delete this override when
    the first DB-touching test lands in this file; the real fix is #319.
    """
    yield


@pytest.fixture
def provider(idp, monkeypatch) -> ProviderConfig:
    """A provider discovered by issuer, so `_discovery` takes the real
    issuer → well-known → httpx path rather than the explicit-URL shortcut."""
    monkeypatch.setattr(
        settings,
        "oauth_providers",
        json.dumps(
            [
                {
                    "id": "stub",
                    "display_name": "Stub IdP",
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "issuer": idp.base,
                }
            ]
        ),
    )
    return get_provider("stub")


@pytest.fixture
def cache() -> TtlCache:
    return TtlCache(ttl_seconds=60)


def _closed_port() -> int:
    """A port nothing listens on: bound, then released."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def test_claims_from_id_token_rejects_wrong_issuer(provider, idp, cache):
    assert (
        await claims_from_id_token(provider, idp.doc, idp.mint(iss="http://evil.example"), cache)
        is None
    )


async def test_claims_from_id_token_rejects_wrong_issuer_without_discovery_doc(
    provider, idp, cache
):
    """A provider configured with explicit endpoints and no discovery document: the
    expected issuer comes from the config, so a foreign `iss` is still rejected."""
    doc = {k: v for k, v in idp.doc.items() if k != "issuer"}
    assert (
        await claims_from_id_token(provider, doc, idp.mint(iss="http://evil.example"), cache)
        is None
    )


async def test_claims_from_id_token_rejects_disagreeing_discovery_issuer(
    provider, idp, cache, caplog
):
    """The config is the pin: a discovery document naming another issuer is
    refused outright, so a compromised or misconfigured IdP cannot repoint the
    check even when it also signs the token it wants accepted."""
    doc = {**idp.doc, "issuer": "http://evil.example"}
    with caplog.at_level(logging.WARNING, logger="src.services.oauth"):
        assert (
            await claims_from_id_token(provider, doc, idp.mint(iss="http://evil.example"), cache)
            is None
        )
    assert "discovery issuer mismatch" in caplog.text


async def test_claims_from_id_token_ignores_trailing_slash_on_issuer(provider, idp, cache):
    """PyJWT compares `iss` byte for byte, so a cosmetic slash must not decide the
    outcome — on the config, the discovery-document or the token side. A
    slash-terminated issuer is a legal OIDC shape (Discovery 1.0 §3)."""
    slashed = replace(provider, issuer=f"{idp.base}/")
    slashed_doc = {**idp.doc, "issuer": f"{idp.base}/"}
    assert (
        await claims_from_id_token(provider, idp.doc, idp.mint(iss=f"{idp.base}/"), cache)
        is not None
    )
    assert await claims_from_id_token(slashed, idp.doc, idp.mint(), cache) is not None
    assert (
        await claims_from_id_token(slashed, slashed_doc, idp.mint(iss=f"{idp.base}/"), cache)
        is not None
    )
    assert (
        await claims_from_id_token(provider, slashed_doc, idp.mint(iss=f"{idp.base}/"), cache)
        is not None
    )


async def test_claims_from_id_token_rejects_non_string_issuer(provider, idp, cache):
    """The document is network-sourced JSON and the config is unvalidated env, so
    `issuer` is untrusted in type as well as value: anything but a string is
    refused, not raised. The callback only catches `OAuthError`, so an escaping
    exception is a 500 with a stack trace. The config-side case is unreachable
    in production -- `get_provider` coerces `issuer` to `str` -- so it asserts
    the guard, not that a bad config is caught upstream."""
    assert (
        await claims_from_id_token(provider, {**idp.doc, "issuer": ["http://x"]}, idp.mint(), cache)
        is None
    )
    assert (
        await claims_from_id_token(replace(provider, issuer=12345), idp.doc, idp.mint(), cache)
        is None
    )


async def test_claims_from_id_token_rejects_unreadable_discovery_issuer(
    provider, idp, cache, caplog
):
    """A non-string document `issuer` is refused even when no `issuer` is configured,
    where it would otherwise normalize to None and leave the pin presence-only. It
    logs as unreadable, not as a mismatch, so a malformed document and a takeover
    stay distinguishable during triage."""
    for unconfigured in (provider, replace(provider, issuer=None)):
        bad_doc = {**idp.doc, "issuer": 12345}
        with caplog.at_level(logging.WARNING, logger="src.services.oauth"):
            assert await claims_from_id_token(unconfigured, bad_doc, idp.mint(), cache) is None
        assert "unreadable issuer in discovery document" in caplog.text
        assert "discovery issuer mismatch" not in caplog.text


async def test_claims_from_id_token_without_issuer_checks_presence_only(provider, idp, cache):
    """Deliberate ceiling: a provider that names no issuer anywhere (the explicit-URL
    shape, e.g. the GitHub config) has nothing to compare `iss` against, so only
    presence is enforced. Configure `issuer` to pin the value."""
    doc = {k: v for k, v in idp.doc.items() if k != "issuer"}
    claims = await claims_from_id_token(replace(provider, issuer=None), doc, idp.mint(), cache)
    assert claims is not None


async def test_claims_from_id_token_accepts_valid_rs256(provider, idp, cache):
    """Positive control: if this fails the harness itself is broken."""
    claims = await claims_from_id_token(provider, idp.doc, idp.mint(), cache)
    assert claims is not None
    assert claims["sub"] == "sub-1"
    assert claims["email"] == "user@example.com"


async def test_claims_from_id_token_accepts_valid_es256(provider, idp, cache):
    """Second half of the RS256/ES256 allow-list: some Entra and Okta configs serve ES256."""
    claims = await claims_from_id_token(
        provider, idp.doc, idp.mint(kid=EC_KID, key=idp.ec_key, alg="ES256"), cache
    )
    assert claims is not None
    assert claims["sub"] == "sub-1"
    assert claims["email"] == "user@example.com"


async def test_claims_from_id_token_rejects_es256_token_signed_by_another_ec_key(
    provider, idp, cache
):
    """Negative control for the ES256 half: same kid, different EC key. Only a real
    signature check catches this, and the RS256 twin says nothing about EC."""
    claims = await claims_from_id_token(
        provider, idp.doc, idp.mint(kid=EC_KID, key=idp.other_ec_key, alg="ES256"), cache
    )
    assert claims is None


async def test_claims_from_id_token_rejects_es256_token_labeled_with_the_rsa_kid(
    provider, idp, cache
):
    """Cross-family control: the JWKS resolves an RSA key for an `alg=ES256` token, so the key type
    rejects it before any signature is checked. The twins keep the kid's key type and swap only the
    private key; here the kid is re-labeled instead. The first mint is valid on its own — a resolver
    trusting the header `alg` over the kid accepts it; the second is the shape an attacker sends."""
    from_published_ec_key = idp.mint(kid=KID, key=idp.ec_key, alg="ES256")
    from_attacker_ec_key = idp.mint(kid=KID, key=idp.other_ec_key, alg="ES256")

    assert await claims_from_id_token(provider, idp.doc, from_published_ec_key, cache) is None
    assert await claims_from_id_token(provider, idp.doc, from_attacker_ec_key, cache) is None


async def test_claims_from_id_token_rejects_rs256_token_labeled_with_the_ec_kid(
    provider, idp, cache
):
    """The mirror direction, so neither key family is the one that goes uncovered."""
    from_published_rsa_key = idp.mint(kid=EC_KID, key=idp.signing_key, alg="RS256")
    from_attacker_rsa_key = idp.mint(kid=EC_KID, key=idp.other_key, alg="RS256")

    assert await claims_from_id_token(provider, idp.doc, from_published_rsa_key, cache) is None
    assert await claims_from_id_token(provider, idp.doc, from_attacker_rsa_key, cache) is None


async def test_claims_from_id_token_rejects_wrong_audience(provider, idp, cache):
    assert (
        await claims_from_id_token(provider, idp.doc, idp.mint(aud="another-client"), cache) is None
    )


async def test_claims_from_id_token_rejects_expired_token(provider, idp, cache):
    token = idp.mint(exp=int(time.time()) - 10)
    assert await claims_from_id_token(provider, idp.doc, token, cache) is None


@pytest.mark.parametrize("claim", ["exp", "iss", "sub"])
async def test_claims_from_id_token_rejects_token_missing_a_required_claim(
    provider, idp, cache, claim
):
    """`options["require"]` enforces presence, `iss`/`aud` enforce value: a token
    missing a required claim must fail even though every present claim is valid."""
    token = idp.mint(drop=(claim,))
    assert await claims_from_id_token(provider, idp.doc, token, cache) is None


async def test_claims_from_id_token_rejects_unknown_kid(provider, idp, cache):
    assert (
        await claims_from_id_token(provider, idp.doc, idp.mint(kid="rotated-away"), cache) is None
    )


async def test_claims_from_id_token_rejects_token_without_a_kid(provider, idp, cache):
    """`PyJWKClient` matches on the token's kid and has no kid-less fallback, so a token
    without one is refused rather than verified against the sole published key. Both halves
    are asserted: no fallback for a kid-less token, and no candidate in a kid-less key."""
    assert await claims_from_id_token(provider, idp.doc, idp.mint(kid=None), cache) is None
    idp.published = [(idp.signing_key, None, "RS256")]
    try:
        assert await claims_from_id_token(provider, idp.doc, idp.mint(kid=None), cache) is None
    finally:
        idp.published = [(idp.signing_key, KID, "RS256"), (idp.ec_key, EC_KID, "ES256")]


async def test_claims_from_id_token_rejects_token_signed_by_another_key(provider, idp, cache):
    """Same kid, different private key: only a real signature check catches this."""
    assert await claims_from_id_token(provider, idp.doc, idp.mint(key=idp.other_key), cache) is None


async def test_claims_from_id_token_rejects_unsigned_token(provider, idp, cache):
    assert await claims_from_id_token(provider, idp.doc, idp.mint(alg="none"), cache) is None


async def test_claims_from_id_token_logs_jwks_fetch_failure(provider, idp, cache, caplog):
    """An unreachable JWKS is an outage, not a bad token. It refuses either way,
    but it must not log under the message a signature failure produces, or an
    IdP key rotation is triaged as a takeover."""
    doc = {**idp.doc, "jwks_uri": f"http://127.0.0.1:{_closed_port()}/jwks"}
    with caplog.at_level(logging.WARNING, logger="src.services.oauth"):
        assert await claims_from_id_token(provider, doc, idp.mint(), cache) is None
    assert "jwks fetch failed" in caplog.text
    assert "id_token verification failed" not in caplog.text


async def test_claims_from_id_token_logs_unknown_kid_as_verification_failure(
    provider, idp, cache, caplog
):
    """The JWKS was fetched and simply does not publish this kid: an attack-shaped
    probe, not an outage, so it must not land on the jwks-fetch line."""
    with caplog.at_level(logging.WARNING, logger="src.services.oauth"):
        assert (
            await claims_from_id_token(provider, idp.doc, idp.mint(kid="rotated-away"), cache)
            is None
        )
    assert "jwks fetch failed" not in caplog.text
    assert "id_token verification failed" in caplog.text


async def test_claims_from_id_token_logs_unparseable_token_as_verification_failure(
    provider, idp, cache, caplog
):
    """An unparseable token names no key a fetch could return, so naming a fetch
    would name an operation that could not have helped."""
    with caplog.at_level(logging.WARNING, logger="src.services.oauth"):
        assert await claims_from_id_token(provider, idp.doc, "not-a-jwt", cache) is None
    assert "jwks fetch failed" not in caplog.text
    assert "id_token verification failed" in caplog.text


async def test_claims_from_id_token_returns_none_without_jwks_uri(provider, idp, cache):
    doc = {k: v for k, v in idp.doc.items() if k != "jwks_uri"}
    assert await claims_from_id_token(provider, doc, idp.mint(), cache) is None


async def test_jwks_is_fetched_once_and_reused(provider, idp, cache):
    """#341: the key set belongs in the TTL cache next to discovery, not refetched per login."""
    before = idp.hits.count("/jwks")
    first = await claims_from_id_token(provider, idp.doc, idp.mint(), cache)
    second = await claims_from_id_token(provider, idp.doc, idp.mint(), cache)
    assert first is not None and second is not None
    assert idp.hits.count("/jwks") == before + 1


async def test_jwks_is_refetched_for_a_rotated_kid(provider, idp, cache):
    """A new kid must not wait out the cache TTL, or every login fails after a key rotation."""
    assert await claims_from_id_token(provider, idp.doc, idp.mint(), cache) is not None
    before = idp.hits.count("/jwks")
    idp.published = [(idp.other_key, ROTATED_KID, "RS256")]
    try:
        claims = await claims_from_id_token(
            provider, idp.doc, idp.mint(key=idp.other_key, kid=ROTATED_KID), cache
        )
    finally:
        idp.published = [(idp.signing_key, KID, "RS256"), (idp.ec_key, EC_KID, "ES256")]
    assert claims is not None
    assert idp.hits.count("/jwks") == before + 1


async def test_jwks_follows_a_redirect(provider, idp, cache):
    """`PyJWKClient` fetched through urllib, which follows redirects; httpx does not
    by default, so without the flag a redirecting `jwks_uri` fails every login."""
    doc = dict(idp.doc, jwks_uri=f"{idp.base}/jwks-redirect")
    assert await claims_from_id_token(provider, doc, idp.mint(), cache) is not None


async def test_unusable_jwks_is_not_served_from_the_cache(provider, idp, cache):
    """A malformed key set must cost only the logins it broke, not the whole cache TTL."""
    doc = dict(idp.doc, jwks_uri=f"{idp.base}/jwks-broken")
    idp.broken_jwks = {"keys": []}
    try:
        assert await claims_from_id_token(provider, doc, idp.mint(), cache) is None
        before = idp.hits.count("/jwks-broken")
        idp.broken_jwks = UNSET
        claims = await claims_from_id_token(provider, doc, idp.mint(), cache)
    finally:
        idp.broken_jwks = UNSET
    assert claims is not None
    assert claims["sub"] == "sub-1"
    assert idp.hits.count("/jwks-broken") == before + 1, "the bad set was served from the cache"


async def test_jwks_without_a_usable_signing_key_is_not_cached(provider, idp, cache, caplog):
    """#1024: `from_dict` parses an encryption-only set, but `_signing_key` can never
    select from it, so caching it costs every later login a kid-miss refetch."""
    doc = dict(idp.doc, jwks_uri=f"{idp.base}/jwks-broken")
    enc_key = _jwk(idp.other_key, "enc-1", "RS256")
    enc_key["use"] = "enc"
    idp.broken_jwks = {"keys": [enc_key]}
    try:
        with caplog.at_level(logging.WARNING, logger="src.services.oauth"):
            assert await claims_from_id_token(provider, doc, idp.mint(), cache) is None
        # #1113: `_failure_detail` reduces anything without a status to its type
        # name, so a gate raised inside the fetch try reached the log as "ValueError".
        assert "no key published for signing" in caplog.text
        assert cache.get(f"oauth:jwks:{provider.id}") is None, "an unusable set was cached"
        before = idp.hits.count("/jwks-broken")
        for _ in range(3):
            assert await claims_from_id_token(provider, doc, idp.mint(), cache) is None
        assert idp.hits.count("/jwks-broken") == before + 3, (
            "the cached set saved nothing, so each login paid a refetch on top of the cache hit"
        )
    finally:
        idp.broken_jwks = UNSET


@pytest.mark.parametrize("broken", [["not", "a", "dict"], "str", 42, None])
async def test_jwks_refuses_a_key_set_that_is_not_an_object(provider, idp, cache, broken, caplog):
    """#1112: `_jwks` is annotated `-> dict[str, Any]` while `resp.json()` is `Any`, so
    the annotation has to be enforced here instead of left to `PyJWKSet.from_dict`."""
    idp.broken_jwks = broken
    doc = dict(idp.doc, jwks_uri=f"{idp.base}/jwks-broken")
    try:
        with caplog.at_level(logging.WARNING, logger="src.services.oauth"):
            assert await claims_from_id_token(provider, doc, idp.mint(), cache) is None
    finally:
        idp.broken_jwks = UNSET
    assert "is not an object" in caplog.text
    assert cache.get(f"oauth:jwks:{provider.id}") is None, "the bad key set was cached"


async def test_concurrent_kid_misses_refetch_once(provider, idp, cache):
    """#1025: a burst of logins meeting an unknown kid shares one in-flight refetch
    instead of paying one outbound JWKS request per login."""
    assert await claims_from_id_token(provider, idp.doc, idp.mint(), cache) is not None
    before = idp.hits.count("/jwks")
    idp.published = [(idp.other_key, ROTATED_KID, "RS256")]
    idp.jwks_delay = 0.05
    try:
        tokens = [idp.mint(key=idp.other_key, kid=ROTATED_KID) for _ in range(5)]
        claims = await asyncio.gather(
            *[claims_from_id_token(provider, idp.doc, t, cache) for t in tokens]
        )
    finally:
        idp.published = [(idp.signing_key, KID, "RS256"), (idp.ec_key, EC_KID, "ES256")]
        idp.jwks_delay = 0.0
    assert all(c is not None for c in claims)
    assert idp.hits.count("/jwks") == before + 1


async def test_concurrent_cold_jwks_fetches_once(provider, idp):
    """#1025: a cold cache under a burst is filled once, not once per login."""
    fresh = TtlCache(ttl_seconds=60)
    before = idp.hits.count("/jwks")
    idp.jwks_delay = 0.05
    try:
        claims = await asyncio.gather(
            *[claims_from_id_token(provider, idp.doc, idp.mint(), fresh) for _ in range(5)]
        )
    finally:
        idp.jwks_delay = 0.0
    assert all(c is not None for c in claims)
    assert idp.hits.count("/jwks") == before + 1


async def test_concurrent_failed_jwks_fetches_fail_together(provider, idp, cache):
    """One unusable set fails the whole burst with the same error, costs one fetch,
    and leaves nothing behind: no cached set, no dead in-flight entry to join."""
    doc = dict(idp.doc, jwks_uri=f"{idp.base}/jwks-broken")
    idp.broken_jwks = {"keys": []}
    before = idp.hits.count("/jwks-broken")
    try:
        outcomes = await asyncio.gather(
            *[_jwks(provider, doc, cache) for _ in range(5)], return_exceptions=True
        )
    finally:
        idp.broken_jwks = UNSET
    assert idp.hits.count("/jwks-broken") == before + 1
    assert all(isinstance(o, OAuthError) for o in outcomes)
    assert cache.get(f"oauth:jwks:{provider.id}") is None, "the failed fetch was cached"
    # The released entry means a later caller fetches again rather than joining
    # a completed failure.
    assert await _jwks(provider, doc, cache) is not None
    assert idp.hits.count("/jwks-broken") == before + 2


async def test_claims_from_id_token_survives_a_non_string_jwks_uri(provider, idp, cache):
    """A `jwks_uri` that is not a string must fail the sign-in, not raise."""
    doc = dict(idp.doc, jwks_uri=12345)
    assert await claims_from_id_token(provider, doc, idp.mint(), cache) is None


async def test_signing_key_is_matched_by_kid_not_position(provider, idp, cache):
    """Key selection is hand-rolled here, so the first published key is not the answer."""
    idp.published = [
        (idp.other_key, "other-kid", "RS256"),
        (idp.signing_key, KID, "RS256"),
        (idp.ec_key, EC_KID, "ES256"),
    ]
    try:
        claims = await claims_from_id_token(provider, idp.doc, idp.mint(), cache)
    finally:
        idp.published = [(idp.signing_key, KID, "RS256"), (idp.ec_key, EC_KID, "ES256")]
    assert claims is not None
    assert claims["sub"] == "sub-1"


async def test_claims_from_id_token_keeps_the_event_loop_responsive(provider, idp, cache):
    """#341: the key fetch has to be async — blocking it on the loop stalls every request."""
    idp.jwks_delay = 0.4
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    beat = asyncio.create_task(ticker())
    try:
        claims = await claims_from_id_token(provider, idp.doc, idp.mint(), cache)
    finally:
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat
        idp.jwks_delay = 0.0
    assert claims is not None
    assert ticks > 5, f"event loop stalled while the JWKS host was slow (ticks={ticks})"


async def test_claims_from_id_token_returns_none_when_the_jwks_host_is_down(
    provider, idp, cache, caplog
):
    """None is what the caller handles, and the log has to say the key endpoint failed
    rather than leaving an operator to read a bad token."""
    doc = dict(idp.doc, jwks_uri=f"http://127.0.0.1:{_closed_port()}/jwks")
    with caplog.at_level(logging.WARNING, logger="src.services.oauth"):
        assert await claims_from_id_token(provider, doc, idp.mint(), cache) is None
    assert "could not load signing keys" in caplog.text


async def test_claims_from_id_token_lets_a_defect_escape(provider, idp, cache, monkeypatch):
    """The handler is narrowed to the failures PyJWT and the IdP produce, so a defect
    in this module or in the provider config has to surface as a traceback rather than
    as a rejected login."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("provider config is malformed")

    monkeypatch.setattr("src.services.oauth.jwt.decode", boom)
    with pytest.raises(RuntimeError, match="provider config is malformed"):
        await claims_from_id_token(provider, idp.doc, idp.mint(), cache)


async def test_claims_from_id_token_lets_a_defect_escape_from_the_key_lookup(
    provider, idp, cache, monkeypatch
):
    """The same rule on the key side: the handler spans the whole try, so a defect in
    the key lookup must not be reported as an unverifiable token either."""

    def boom(*_args, **_kwargs):
        raise AttributeError("signing key has no key attribute")

    monkeypatch.setattr("src.services.oauth._signing_key", boom)
    with pytest.raises(AttributeError, match="no key attribute"):
        await claims_from_id_token(provider, idp.doc, idp.mint(), cache)


@pytest.mark.parametrize(
    ("flag", "cause"),
    [
        ("garbage_jwks", "JSONDecodeError"),
        ("undecodable_jwks", "UnicodeDecodeError"),
        ("truncated_jwks", "RemoteProtocolError"),
    ],
    ids=["non-json-body", "non-utf8-body", "body-cut-off-mid-stream"],
)
async def test_an_unreadable_jwks_body_names_the_cause(
    provider, idp, cache, caplog, monkeypatch, flag, cause
):
    """A JWKS URL answered with something no key set can be read from is an outage,
    not a bad signature. Each of these is a different family, and all of them have to
    degrade to the logged `None` the caller falls back from."""
    monkeypatch.setattr(idp, flag, True)
    with caplog.at_level(logging.WARNING, logger="src.services.oauth"):
        assert await claims_from_id_token(provider, idp.doc, idp.mint(), cache) is None
    assert cause in caplog.text


async def test_a_rejected_token_names_the_pyjwt_error(provider, idp, cache, caplog):
    """PyJWT's messages are prose, so the log line carries the class name: an operator
    separates an expired token from a wrong audience without knowing PyJWT's wording."""
    with caplog.at_level(logging.WARNING, logger="src.services.oauth"):
        expired = idp.mint(exp=int(time.time()) - 10)
        assert await claims_from_id_token(provider, idp.doc, expired, cache) is None
    assert "ExpiredSignatureError" in caplog.text


async def test_non_http_jwks_uri_is_never_read(provider, idp, cache, caplog):
    """A `file://` jwks_uri must not read the host's filesystem. httpx refuses the
    scheme before any I/O, so it degrades like any other unreadable key set."""
    doc = dict(idp.doc, jwks_uri="file:///etc/passwd")
    with caplog.at_level(logging.WARNING, logger="src.services.oauth"):
        assert await claims_from_id_token(provider, doc, idp.mint(), cache) is None
    assert "UnsupportedProtocol" in caplog.text


async def test_discovery_fetches_and_caches(provider, idp, cache):
    before = len(idp.hits)

    doc = await _discovery(provider, cache)
    assert doc["issuer"] == idp.base
    assert doc["token_endpoint"] == f"{idp.base}/token"
    assert doc["userinfo_endpoint"] == f"{idp.base}/userinfo"
    assert doc["jwks_uri"] == f"{idp.base}/jwks"
    assert len(idp.hits) == before + 1

    await _discovery(provider, cache)
    assert len(idp.hits) == before + 1, "second call should be served from the TTL cache"


async def test_discovery_raises_oauth_error_when_unreachable():
    dead = ProviderConfig(
        id="dead",
        display_name="Dead IdP",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        issuer=f"http://127.0.0.1:{_closed_port()}",
    )
    with pytest.raises(OAuthError, match="could not load discovery document"):
        await _discovery(dead, TtlCache(ttl_seconds=60))


async def test_discovery_raises_oauth_error_on_a_500_response(provider, idp, cache):
    bad = replace(provider, discovery_url=f"{idp.base}/.well-known/openid-configuration-500")
    with pytest.raises(OAuthError, match="could not load discovery document"):
        await _discovery(bad, cache)
    assert cache.get(f"oauth:discovery:{provider.id}") is None, "the failed document was cached"


async def test_discovery_raises_oauth_error_on_a_non_json_body(provider, idp, cache):
    bad = replace(provider, discovery_url=f"{idp.base}/.well-known/openid-configuration-text")
    with pytest.raises(OAuthError, match="could not load discovery document"):
        await _discovery(bad, cache)
    assert cache.get(f"oauth:discovery:{provider.id}") is None, "the failed document was cached"


@pytest.mark.parametrize("broken", [["not", "a", "dict"], "str", 42, None])
async def test_discovery_refuses_a_document_that_is_not_an_object(provider, idp, cache, broken):
    """#1020: the callback catches only `OAuthError`, so a non-object document has to
    fail here or its `AttributeError` escapes as a 500."""
    idp.broken_doc = broken
    doc_provider = replace(
        provider, discovery_url=f"{idp.base}/.well-known/openid-configuration-broken"
    )
    try:
        with pytest.raises(OAuthError, match="is not an object"):
            await _discovery(doc_provider, cache)
    finally:
        idp.broken_doc = UNSET
    assert cache.get(f"oauth:discovery:{provider.id}") is None, "the bad document was cached"


async def test_concurrent_discovery_fetches_once(provider, idp):
    """#1025: the discovery path has the same burst shape — five cold callers, one
    well-known fetch."""
    fresh = TtlCache(ttl_seconds=60)

    def known() -> int:
        return sum(1 for h in idp.hits if h.startswith("/.well-known"))

    before = known()
    idp.discovery_delay = 0.05
    try:
        docs = await asyncio.gather(*[_discovery(provider, fresh) for _ in range(5)])
    finally:
        idp.discovery_delay = 0.0
    assert all(d["issuer"] == idp.base for d in docs)
    assert known() == before + 1


def test_authorize_url_carries_s256_challenge(provider, idp):
    """The challenge in the redirect must be the S256 digest of the verifier
    the server kept: the client only ever sees the public half."""
    cache = TtlCache(ttl_seconds=60)

    params = parse_qs(urlsplit(build_authorize_url(provider, idp.doc, cache, REDIRECT_URI)).query)

    assert params["code_challenge_method"] == ["S256"]
    assert "code_verifier" not in params
    verifier = consume_state(cache, params["state"][0])["code_verifier"]
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    assert params["code_challenge"] == [expected.rstrip(b"=").decode()]


def test_consume_state_rejects_entry_without_verifier(provider):
    """An entry carrying no verifier would mint a verifier-less exchange, the one
    request the challenge exists to prevent."""
    cache = TtlCache(ttl_seconds=60)
    cache.set(STATE_TTL_HINT + "s", {"provider": provider.id, "redirect_uri": REDIRECT_URI})

    with pytest.raises(OAuthError, match="invalid or expired state"):
        consume_state(cache, "s")


async def test_exchange_code_posts_grant_and_returns_tokens(provider, idp):
    tokens = await exchange_code(
        provider,
        idp.doc,
        code="good-code",
        redirect_uri=REDIRECT_URI,
        code_verifier="verifier-abc",
    )

    assert tokens["access_token"] == "at-stub"
    form = idp.token_forms[-1]
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["good-code"]
    assert form["redirect_uri"] == [REDIRECT_URI]
    assert form["client_id"] == [CLIENT_ID]
    assert form["client_secret"] == [CLIENT_SECRET]
    assert form["code_verifier"] == ["verifier-abc"]


async def test_exchange_code_raises_on_provider_error(provider, idp, caplog):
    with caplog.at_level("WARNING", logger="src.services.oauth"):
        with pytest.raises(OAuthError, match="code exchange failed"):
            await exchange_code(
                provider,
                idp.doc,
                code="bad-code",
                redirect_uri=REDIRECT_URI,
                code_verifier="verifier-abc",
            )
    # The body is what separates a rejected code_verifier from an expired code.
    assert "invalid_grant" in caplog.text


async def test_exchange_code_flattens_cr_in_the_logged_provider_body(provider, idp, caplog):
    """A bare CR overwrites the line it lands on, so it is flattened like the LF."""
    idp.token_error_body = '{"error": "invalid_grant\rforged: 500"}'
    try:
        with caplog.at_level("WARNING", logger="src.services.oauth"):
            with pytest.raises(OAuthError, match="code exchange failed"):
                await exchange_code(
                    provider,
                    idp.doc,
                    code="bad-code",
                    redirect_uri=REDIRECT_URI,
                    code_verifier="verifier-abc",
                )
    finally:
        idp.token_error_body = None

    assert "invalid_grant forged: 500" in caplog.text
    assert "\r" not in caplog.text


async def test_claims_from_id_token_flattens_cr_in_the_logged_failure(provider, idp, cache, caplog):
    """Mirror of the exchange_code test: the logged exception can embed token-supplied
    header data, so CR and LF are flattened. `crit` is the vehicle because PyJWT echoes
    only it into the message; an unknown `kid` raises fixed strings."""
    evil = "x\rforged:\n500"
    token = idp.mint(kid=evil, extra_headers={"crit": [evil], evil: True})
    with caplog.at_level("WARNING", logger="src.services.oauth"):
        assert await claims_from_id_token(provider, idp.doc, token, cache) is None
    assert "x forged: 500" in caplog.text
    assert "\r" not in caplog.text
    record = next(r for r in caplog.records if "id_token verification failed" in r.getMessage())
    assert "\r" not in record.getMessage()
    assert "\n" not in record.getMessage()


@pytest.mark.parametrize("broken", [["not", "a", "dict"], "str", 42, None])
async def test_exchange_code_refuses_a_response_that_is_not_an_object(provider, idp, broken):
    """#1112: the callback catches only `OAuthError` and then reads `tokens.get(...)`, so
    a non-object body has to fail here or its `AttributeError` escapes as a 500."""
    idp.broken_tokens = broken
    try:
        with pytest.raises(OAuthError, match="is not an object"):
            await exchange_code(
                provider,
                idp.doc,
                code="good-code",
                redirect_uri=REDIRECT_URI,
                code_verifier="verifier-abc",
            )
    finally:
        idp.broken_tokens = UNSET


async def test_fetch_userinfo_sends_bearer_token(provider, idp):
    info = await fetch_userinfo(provider, idp.doc, "at-stub")

    assert idp.auth_headers[-1] == "Bearer at-stub"
    assert info["email"] == "user@example.com"


async def test_fetch_userinfo_raises_on_provider_error(provider, idp):
    doc = dict(idp.doc, userinfo_endpoint=f"{idp.base}/userinfo?mode=500")
    with pytest.raises(OAuthError, match="could not fetch user info"):
        await fetch_userinfo(provider, doc, "at-stub")


async def test_fetch_userinfo_returns_empty_for_a_response_that_is_not_an_object(provider, idp):
    doc = dict(idp.doc, userinfo_endpoint=f"{idp.base}/userinfo?mode=array")
    assert await fetch_userinfo(provider, doc, "at-stub") == {}


def test_single_line_replaces_every_cc_control_with_a_space():
    # C0 (CR/LF/ESC), DEL, C1 (NEL): the ESC is defused so "[31m" that follows
    # is inert text, and no control can forge a log line.
    assert _single_line("a\rb\nc\x1b[31md\x7fe\x85") == "a b c [31md e "


def test_single_line_truncates_to_the_cap():
    assert _single_line("x" * 300) == "x" * 200
