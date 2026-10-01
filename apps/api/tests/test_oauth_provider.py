"""Real-provider coverage for the OIDC path.

The pre-existing OAuth tests monkeypatch `_discovery`, `exchange_code` and
`fetch_userinfo` at the service-module boundary, so none of them ever run. This
file drives them for real against an in-process IdP — a `ThreadingHTTPServer`
on `127.0.0.1:0` serving a discovery document, an RS256 JWKS, a token endpoint
and a userinfo endpoint. No network egress, no mocked seams, no new dependency
(`pyjwt`, `cryptography` and `httpx` are already runtime deps).

`httpx.MockTransport` would not do: `jwt.PyJWKClient` fetches keys with
`urllib.request`, so a transport-level httpx mock never sees the key fetch. A
real socket is the only way to exercise signature handling as written.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

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
EC_KID = "stub-ec-1"
REDIRECT_URI = "http://localhost:8000/api/v1/auth/oauth/stub/callback"


def _jwk(key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey, kid: str, alg: str) -> dict[str, Any]:
    algo = {"RS256": jwt.algorithms.RSAAlgorithm, "ES256": jwt.algorithms.ECAlgorithm}[alg]
    pub = json.loads(algo.to_jwk(key.public_key()))
    return {**pub, "kid": kid, "use": "sig", "alg": alg}


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
        key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | None = None,
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
                    keys = [
                        _jwk(stub.signing_key, KID, "RS256"),
                        _jwk(stub.ec_key, EC_KID, "ES256"),
                    ]
                    self._send(200, {"keys": keys})
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

    These tests never touch the database, and each default unlink/recreate cycle
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


def _closed_port() -> int:
    """A port nothing listens on: bound, then released."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_claims_from_id_token_rejects_wrong_issuer(provider, idp):
    assert claims_from_id_token(provider, idp.doc, idp.mint(iss="http://evil.example")) is None


def test_claims_from_id_token_rejects_wrong_issuer_without_discovery_doc(provider, idp):
    """A provider configured with explicit endpoints and no discovery document: the
    expected issuer comes from the config, so a foreign `iss` is still rejected."""
    doc = {k: v for k, v in idp.doc.items() if k != "issuer"}
    assert claims_from_id_token(provider, doc, idp.mint(iss="http://evil.example")) is None


def test_claims_from_id_token_without_issuer_checks_presence_only(provider, idp):
    """Deliberate ceiling: a provider that names no issuer anywhere (the explicit-URL
    shape, e.g. the GitHub config) has nothing to compare `iss` against, so only
    presence is enforced. Configure `issuer` to pin the value."""
    doc = {k: v for k, v in idp.doc.items() if k != "issuer"}
    assert claims_from_id_token(replace(provider, issuer=None), doc, idp.mint()) is not None


def test_claims_from_id_token_accepts_valid_rs256(provider, idp):
    """Positive control: if this fails the harness itself is broken."""
    claims = claims_from_id_token(provider, idp.doc, idp.mint())
    assert claims is not None
    assert claims["sub"] == "sub-1"
    assert claims["email"] == "user@example.com"


def test_claims_from_id_token_accepts_valid_es256(provider, idp):
    """Second half of the RS256/ES256 allow-list: some Entra and Okta configs serve ES256."""
    claims = claims_from_id_token(
        provider, idp.doc, idp.mint(kid=EC_KID, key=idp.ec_key, alg="ES256")
    )
    assert claims is not None
    assert claims["sub"] == "sub-1"
    assert claims["email"] == "user@example.com"


def test_claims_from_id_token_rejects_es256_token_signed_by_another_ec_key(provider, idp):
    """Negative control for the ES256 half: same kid, different EC key. Only a real
    signature check catches this, and the RS256 twin says nothing about EC."""
    claims = claims_from_id_token(
        provider, idp.doc, idp.mint(kid=EC_KID, key=idp.other_ec_key, alg="ES256")
    )
    assert claims is None


def test_jwk_rejects_unknown_algorithm(idp):
    """An alg outside the map raises here, at the call site. The ternary this replaced
    emitted an RSA key labelled with whatever alg it was handed, so the stub published
    a key it could never verify and the failure surfaced as a signature error."""
    with pytest.raises(KeyError):
        _jwk(idp.signing_key, "kid-x", "PS256")


def test_claims_from_id_token_rejects_wrong_audience(provider, idp):
    assert claims_from_id_token(provider, idp.doc, idp.mint(aud="another-client")) is None


def test_claims_from_id_token_rejects_expired_token(provider, idp):
    assert claims_from_id_token(provider, idp.doc, idp.mint(exp=int(time.time()) - 10)) is None


def test_claims_from_id_token_rejects_unknown_kid(provider, idp):
    assert claims_from_id_token(provider, idp.doc, idp.mint(kid="rotated-away")) is None


def test_claims_from_id_token_rejects_token_signed_by_another_key(provider, idp):
    """Same kid, different private key: only a real signature check catches this."""
    assert claims_from_id_token(provider, idp.doc, idp.mint(key=idp.other_key)) is None


def test_claims_from_id_token_rejects_unsigned_token(provider, idp):
    assert claims_from_id_token(provider, idp.doc, idp.mint(alg="none")) is None


def test_claims_from_id_token_returns_none_without_jwks_uri(provider, idp):
    doc = {k: v for k, v in idp.doc.items() if k != "jwks_uri"}
    assert claims_from_id_token(provider, doc, idp.mint()) is None


async def test_discovery_fetches_and_caches(provider, idp):
    cache = TtlCache(ttl_seconds=60)
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
