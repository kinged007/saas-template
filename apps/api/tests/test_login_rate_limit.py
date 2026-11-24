"""Login rate limits: account budget across IPs plus lockout after exhaustion.

The (IP, email) key alone is bypassed by rotating source addresses, so POST
/auth/login also charges `account:<email>` — one inbox attacked from many IPs
shares one budget. Spending the window budget locks the key for
AUTH_RATE_LIMIT_LOCKOUT_SECONDS instead of merely sliding the window.
"""

from __future__ import annotations

from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from src.api.routes.auth import _account_limit_key
from src.core.security.ratelimit import SlidingWindowLimiter, get_auth_limiter
from src.settings import settings
from tests.conftest import register_user


def _check(limiter, key):
    try:
        limiter.check(key)
    except HTTPException as exc:
        return exc
    return None


def test_lockout_pins_retry_after_to_lockout():
    limiter = SlidingWindowLimiter(max_attempts=2, window_seconds=60, lockout_seconds=900)
    limiter.check("k")
    limiter.fail("k")
    limiter.check("k")
    limiter.fail("k")
    exc = _check(limiter, "k")
    assert exc is not None
    assert exc.status_code == 429
    assert exc.headers["Retry-After"] == "900"


def test_reset_clears_lockout():
    limiter = SlidingWindowLimiter(max_attempts=1, window_seconds=60, lockout_seconds=900)
    limiter.check("k")
    limiter.fail("k")
    assert _check(limiter, "k") is not None
    limiter.reset("k")
    assert _check(limiter, "k") is None


def test_zero_lockout_falls_back_to_window_math():
    limiter = SlidingWindowLimiter(max_attempts=1, window_seconds=60, lockout_seconds=0)
    limiter.check("k")
    limiter.fail("k")
    exc = _check(limiter, "k")
    assert exc is not None
    assert exc.status_code == 429
    # window math: the single hit plus the 60 s window, not a lockout
    assert 1 <= int(exc.headers["Retry-After"]) <= 61


def test_clear_drops_locks():
    limiter = SlidingWindowLimiter(max_attempts=1, window_seconds=60, lockout_seconds=900)
    limiter.check("k")
    limiter.fail("k")
    assert _check(limiter, "k") is not None
    limiter.clear()
    assert _check(limiter, "k") is None


def test_account_key_normalizes_case():
    assert _account_limit_key("Victim@Example.COM") == "account:victim@example.com"


async def test_success_resets_both_budgets(app_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 2)
    client = app_client
    await register_user(client, "reset-budget@example.com")
    bad = {"email": "reset-budget@example.com", "password": "Wrong123!"}
    good = {"email": "reset-budget@example.com", "password": "Password123!"}

    assert (await client.post("/api/v1/auth/login", json=bad)).status_code == 401
    assert (await client.post("/api/v1/auth/login", json=good)).status_code == 200
    # the success above reset both keys, so the budget is whole again
    assert (await client.post("/api/v1/auth/login", json=bad)).status_code == 401
    assert (await client.post("/api/v1/auth/login", json=bad)).status_code == 401
    capped = await client.post("/api/v1/auth/login", json=bad)
    assert capped.status_code == 429, capped.text
    assert "Retry-After" in capped.headers


async def test_lockout_retry_after_names_lockout(app_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 1)
    monkeypatch.setattr(settings, "auth_rate_limit_window_seconds", 300)
    monkeypatch.setattr(settings, "auth_rate_limit_lockout_seconds", 60)
    client = app_client
    await register_user(client, "lockout-retry@example.com")
    bad = {"email": "lockout-retry@example.com", "password": "Wrong123!"}

    assert (await client.post("/api/v1/auth/login", json=bad)).status_code == 401
    capped = await client.post("/api/v1/auth/login", json=bad)
    assert capped.status_code == 429, capped.text
    # a pure sliding window would name ~300 s; the lockout names its own 60 s
    assert capped.headers["Retry-After"] == "60"


async def test_account_budget_blocks_distributed_guessing(app, monkeypatch):
    """Two failures from IP-A exhaust the victim's account budget, so IP-B —
    an address that never failed anything — is still capped for that inbox."""
    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 2)
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("203.0.113.7", 40000)),
        base_url="http://test",
    ) as ip_a:
        async with AsyncClient(
            transport=ASGITransport(app=app, client=("198.51.100.9", 40000)),
            base_url="http://test",
        ) as ip_b:
            await register_user(ip_a, "distributed-victim@example.com")
            await register_user(ip_a, "distributed-other@example.com")
            bad = {"email": "distributed-victim@example.com", "password": "Wrong123!"}

            assert (await ip_a.post("/api/v1/auth/login", json=bad)).status_code == 401
            assert (await ip_a.post("/api/v1/auth/login", json=bad)).status_code == 401

            good = {"email": "distributed-victim@example.com", "password": "Password123!"}
            capped = await ip_b.post("/api/v1/auth/login", json=good)
            assert capped.status_code == 429, capped.text

            # a different inbox from the fresh address is untouched
            other = {"email": "distributed-other@example.com", "password": "Password123!"}
            assert (await ip_b.post("/api/v1/auth/login", json=other)).status_code == 200


async def test_prefilled_account_budget_caps_first_attempt(app_client, monkeypatch):
    """Failures recorded under the account key alone (as other replicas or
    addresses would leave them) cap the next login without any IP history."""
    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 3)
    client = app_client
    await register_user(client, "prefilled@example.com")

    limiter = get_auth_limiter()
    for _ in range(3):
        limiter.fail(_account_limit_key("prefilled@example.com"))

    good = {"email": "prefilled@example.com", "password": "Password123!"}
    capped = await client.post("/api/v1/auth/login", json=good)
    assert capped.status_code == 429, capped.text
    # clearing the account budget (a lapsed lockout) unblocks the inbox
    limiter.reset(_account_limit_key("prefilled@example.com"))
    assert (await client.post("/api/v1/auth/login", json=good)).status_code == 200
