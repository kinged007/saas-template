"""Wildcard CORS_ORIGINS entries must pass the cookie CSRF origin check too."""

import re

import pytest
from fastapi import HTTPException, Request

from src.core.security.cookies import _origin_allowed
from src.settings import Settings


@pytest.fixture
def wildcard_cors(monkeypatch):
    monkeypatch.setattr(
        "src.core.security.cookies.settings",
        Settings(cors_origins="http://localhost:5173,*.coder.munyard.biz"),
    )


def test_wildcard_origin_allowed(wildcard_cors):
    assert _origin_allowed("https://5273--main--orca.coder.munyard.biz")
    assert _origin_allowed("https://app.coder.munyard.biz:8443")
    assert _origin_allowed("http://localhost:5173")


def test_other_origins_rejected(wildcard_cors):
    for url in (
        "https://coder.munyard.biz",  # wildcard needs a subdomain
        "https://a.coder.munyard.biz.evil.com",
        "https://evil.com",
        "https://localhost:5173",
    ):
        assert not _origin_allowed(url), url


def test_garbage_url_rejected(wildcard_cors):
    assert not _origin_allowed("")
    assert not _origin_allowed("/login")


def test_require_csrf_accepts_wildcard_referer(wildcard_cors):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/refresh",
            "headers": [
                (b"referer", b"https://app.coder.munyard.biz/settings"),
                (b"x-requested-with", b"XMLHttpRequest"),
            ],
        }
    )
    from src.core.security.cookies import require_csrf

    require_csrf(request)  # no raise


def test_require_csrf_still_blocks_foreign_referer(wildcard_cors):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/refresh",
            "headers": [
                (b"referer", b"https://evil.com/login"),
                (b"x-requested-with", b"XMLHttpRequest"),
            ],
        }
    )
    from src.core.security.cookies import require_csrf

    with pytest.raises(HTTPException) as exc:
        require_csrf(request)
    assert exc.value.status_code == 403


def test_require_csrf_still_requires_header(wildcard_cors):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/refresh",
            "headers": [(b"origin", b"https://app.coder.munyard.biz")],
        }
    )
    from src.core.security.cookies import require_csrf

    with pytest.raises(HTTPException) as exc:
        require_csrf(request)
    assert exc.value.status_code == 403


def test_regex_is_fullmatch_not_prefix():
    pattern = Settings(cors_origins="*.coder.munyard.biz").cors_origin_regex
    assert re.fullmatch(pattern or "", "https://a.coder.munyard.biz")
    assert not re.fullmatch(pattern or "", "https://a.coder.munyard.biz.evil.com")
