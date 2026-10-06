"""#1343: /auth/register meters the verification mail it sends per IP.

The (IP, email) budgets of #1289/#1313 cannot bound registration mail: the
registrant owns every fresh address, so each attempt is a new key. The route
spends a separate per-IP window instead — own limiter instance, not the auth
limiter's (IP, email) budget.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from src.settings import settings


def _register_body(email: str) -> dict:
    return {
        "email": email,
        "password": "Password123!",
        "first_name": "Meter",
        "last_name": "Test",
    }


def _capture_sends(monkeypatch) -> list:
    sent: list = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr("src.email.factory.send_email", _send)
    return sent


async def test_register_meters_mail_per_ip(app_client, monkeypatch):
    """#1343: distinct emails do not reset the meter — the cap is the IP."""
    sent = _capture_sends(monkeypatch)
    monkeypatch.setattr(settings, "auth_register_rate_limit_max_attempts", 2)

    for i in range(2):
        resp = await app_client.post(
            "/api/v1/auth/register", json=_register_body(f"meter-{i}@example.com")
        )
        assert resp.status_code == 201, resp.text
    assert len(sent) == 2

    resp = await app_client.post(
        "/api/v1/auth/register", json=_register_body("meter-capped@example.com")
    )
    assert resp.status_code == 429, resp.text
    assert "Retry-After" in resp.headers
    assert len(sent) == 2  # the capped call sends nothing


async def test_register_failed_attempts_do_not_spend_budget(app_client, monkeypatch):
    """#1343: only sends meter — 422 validation and 409 duplicates stay free."""
    sent = _capture_sends(monkeypatch)
    monkeypatch.setattr(settings, "auth_register_rate_limit_max_attempts", 2)

    resp = await app_client.post(
        "/api/v1/auth/register",
        json={"email": "meter-fail@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 422, resp.text

    first = await app_client.post(
        "/api/v1/auth/register", json=_register_body("meter-a@example.com")
    )
    assert first.status_code == 201, first.text
    dup = await app_client.post("/api/v1/auth/register", json=_register_body("meter-a@example.com"))
    assert dup.status_code == 409, dup.text
    second = await app_client.post(
        "/api/v1/auth/register", json=_register_body("meter-b@example.com")
    )
    assert second.status_code == 201, second.text  # the 409 spent nothing

    resp = await app_client.post(
        "/api/v1/auth/register", json=_register_body("meter-c@example.com")
    )
    assert resp.status_code == 429, resp.text
    assert len(sent) == 2


async def test_register_budget_does_not_throttle_forgot_password(app_client, monkeypatch):
    """#1343: the register window is a separate limiter and key space —
    exhausting it leaves the (IP, email) budgets untouched."""
    sent = _capture_sends(monkeypatch)
    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 2)
    monkeypatch.setattr(settings, "auth_register_rate_limit_max_attempts", 2)

    for i in range(2):
        resp = await app_client.post(
            "/api/v1/auth/register", json=_register_body(f"meter-sep-{i}@example.com")
        )
        assert resp.status_code == 201, resp.text
    capped = await app_client.post(
        "/api/v1/auth/register", json=_register_body("meter-sep-cap@example.com")
    )
    assert capped.status_code == 429, capped.text

    # forgot-password keeps its own (IP, email) budget: two sends still pass.
    for _ in range(2):
        resp = await app_client.post(
            "/api/v1/auth/forgot-password", json={"email": "meter-sep-0@example.com"}
        )
        assert resp.status_code == 202, resp.text
    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "meter-sep-0@example.com"}
    )
    assert resp.status_code == 429, resp.text
    assert len(sent) == 4  # two registrations, two forgot sends, cap sends nothing


async def test_register_budget_is_per_ip(app, monkeypatch):
    """#1343: distinct client IPs get distinct windows."""
    sent = _capture_sends(monkeypatch)
    monkeypatch.setattr(settings, "auth_register_rate_limit_max_attempts", 1)

    async with AsyncClient(
        transport=ASGITransport(app=app, client=("203.0.113.5", 40000)),
        base_url="http://test",
    ) as ip_a:
        async with AsyncClient(
            transport=ASGITransport(app=app, client=("198.51.100.9", 40000)),
            base_url="http://test",
        ) as ip_b:
            first = await ip_a.post(
                "/api/v1/auth/register", json=_register_body("meter-ip-a@example.com")
            )
            assert first.status_code == 201, first.text
            other = await ip_b.post(
                "/api/v1/auth/register", json=_register_body("meter-ip-b@example.com")
            )
            assert other.status_code == 201, other.text
            again = await ip_a.post(
                "/api/v1/auth/register", json=_register_body("meter-ip-a2@example.com")
            )
            assert again.status_code == 429, again.text
    assert len(sent) == 2
