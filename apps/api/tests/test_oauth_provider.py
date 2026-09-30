"""Real-provider coverage for the OIDC path.

The pre-existing OAuth tests monkeypatch `_discovery`, `exchange_code` and
`fetch_userinfo` at the service-module boundary, so none of them ever run. This
file drives them for real against an in-process IdP — a `ThreadingHTTPServer`
on `127.0.0.1:0` serving a discovery document, an RS256 JWKS, a token endpoint
and a userinfo endpoint. No network egress, no mocked seams, no new dependency
(`pyjwt`, `cryptography` and `httpx` are already runtime deps).

`httpx.MockTransport` would not do: the key set has to come off a real socket
for the fetch itself to be measurable. A real HTTP server is the only way to
exercise key resolution and signature handling as written.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from src.core.cache import TtlCache
from src.services.oauth import (
    OAuthError,
    ProviderConfig,
    _discovery,
    claims_from_id_token,
    exchange_code,
    fetch_userinfo,
    get_provider,
)
from src.settings import settings

CLIENT_ID = "cid"
CLIENT_SECRET = "csecret"
KID = "stub-key-1"
ROTATED_KID = "stub-key-2"
REDIRECT_URI = "http://localhost:8000/api/v1/auth/oauth/stub/callback"


def _jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    pub = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {**pub, "kid": kid, "use": "sig", "alg": "RS256"}


class _StubIdP:
    """A real HTTP server speaking just enough OIDC to drive the client code.

    Records what it was asked for (`hits`, `token_forms`, `auth_headers`) so the
    tests can assert on the request, not only on the response.
    """

    def __init__(self) -> None:
        self.signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.hits: list[str] = []
        self.token_forms: list[dict[str, list[str]]] = []
        self.auth_headers: list[str] = []
        # Published key set, mutable so a test can rotate it mid-cache.
        self.published: tuple[rsa.RSAPrivateKey, str] = (self.signing_key, KID)
        self.jwks_delay = 0.0
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
        kid: str = KID,
        key: rsa.RSAPrivateKey | None = None,
        alg: str = "RS256",
        **claims: Any,
    ) -> str:
        """A signed id_token; every claim is overridable so tests can break one at a time."""
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
        if alg == "none":
            return jwt.encode(payload, key="", algorithm="none", headers={"kid": kid})
        return jwt.encode(payload, key or self.signing_key, algorithm=alg, headers={"kid": kid})

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                pass  # keep the access log out of the test output

            def _send(self, code: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                stub.hits.append(self.path)
                if self.path.startswith("/.well-known/openid-configuration"):
                    self._send(200, stub.doc)
                elif self.path == "/jwks":
                    if stub.jwks_delay:
                        time.sleep(stub.jwks_delay)
                    self._send(200, {"keys": [_jwk(*stub.published)]})
                elif self.path == "/userinfo":
                    stub.auth_headers.append(self.headers.get("Authorization", ""))
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
                    self._send(400, {"error": "invalid_grant"})
                else:
                    self._send(
                        200,
                        {
                            "access_token": "at-stub",
                            "token_type": "Bearer",
                            "id_token": stub.mint(),
                        },
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

    These tests never touch the database, and each default drop/recreate cycle
    churns the SQLite file the whole suite shares (#319). Skipping it here keeps
    13 pointless teardowns out of every full run.
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


@pytest.mark.xfail(
    strict=True,
    reason="claims_from_id_token passes audience= to jwt.decode but no issuer=, and PyJWT's "
    "_validate_iss returns immediately when issuer is None — so the iss entry in "
    "options['require'] enforces presence only, never value. Filed as #340; the "
    "strict xfail flips red the day issuer= is added.",
)
async def test_claims_from_id_token_rejects_wrong_issuer(provider, idp, cache):
    assert (
        await claims_from_id_token(provider, idp.doc, idp.mint(iss="http://evil.example"), cache)
        is None
    )


async def test_claims_from_id_token_accepts_valid_rs256(provider, idp, cache):
    """Positive control: if this fails the harness itself is broken."""
    claims = await claims_from_id_token(provider, idp.doc, idp.mint(), cache)
    assert claims is not None
    assert claims["sub"] == "sub-1"
    assert claims["email"] == "user@example.com"


async def test_claims_from_id_token_rejects_wrong_audience(provider, idp, cache):
    assert (
        await claims_from_id_token(provider, idp.doc, idp.mint(aud="another-client"), cache) is None
    )


async def test_claims_from_id_token_rejects_expired_token(provider, idp, cache):
    token = idp.mint(exp=int(time.time()) - 10)
    assert await claims_from_id_token(provider, idp.doc, token, cache) is None


async def test_claims_from_id_token_rejects_unknown_kid(provider, idp, cache):
    assert (
        await claims_from_id_token(provider, idp.doc, idp.mint(kid="rotated-away"), cache) is None
    )


async def test_claims_from_id_token_rejects_token_signed_by_another_key(provider, idp, cache):
    """Same kid, different private key: only a real signature check catches this."""
    assert await claims_from_id_token(provider, idp.doc, idp.mint(key=idp.other_key), cache) is None


async def test_claims_from_id_token_rejects_unsigned_token(provider, idp, cache):
    assert await claims_from_id_token(provider, idp.doc, idp.mint(alg="none"), cache) is None


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
    idp.published = (idp.other_key, ROTATED_KID)
    try:
        claims = await claims_from_id_token(
            provider, idp.doc, idp.mint(key=idp.other_key, kid=ROTATED_KID), cache
        )
    finally:
        idp.published = (idp.signing_key, KID)
    assert claims is not None
    assert idp.hits.count("/jwks") == before + 1


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


async def test_claims_from_id_token_returns_none_when_the_jwks_host_is_down(provider, idp, cache):
    doc = dict(idp.doc, jwks_uri=f"http://127.0.0.1:{_closed_port()}/jwks")
    assert await claims_from_id_token(provider, doc, idp.mint(), cache) is None


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


async def test_exchange_code_posts_grant_and_returns_tokens(provider, idp):
    tokens = await exchange_code(provider, idp.doc, code="good-code", redirect_uri=REDIRECT_URI)

    assert tokens["access_token"] == "at-stub"
    form = idp.token_forms[-1]
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["good-code"]
    assert form["redirect_uri"] == [REDIRECT_URI]
    assert form["client_id"] == [CLIENT_ID]
    assert form["client_secret"] == [CLIENT_SECRET]


async def test_exchange_code_raises_on_provider_error(provider, idp):
    with pytest.raises(OAuthError, match="code exchange failed"):
        await exchange_code(provider, idp.doc, code="bad-code", redirect_uri=REDIRECT_URI)


async def test_fetch_userinfo_sends_bearer_token(provider, idp):
    info = await fetch_userinfo(provider, idp.doc, "at-stub")

    assert idp.auth_headers[-1] == "Bearer at-stub"
    assert info["email"] == "user@example.com"
