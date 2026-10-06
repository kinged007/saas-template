"""Password recovery + email verification (issue #12)."""

from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


async def test_register_sends_verification_and_verify_flow(app_client, monkeypatch):
    import src.email.factory as factory

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    tokens = await register_user(app_client, "verify@example.com")
    assert any("verify-email" in m.text_body for m in sent), [m.text_body for m in sent]

    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.status_code == 200
    assert me.json()["email_verified"] is False

    # extract raw token from the email link
    link = next(m for m in sent if "verify-email" in m.text_body)
    raw = link.text_body.split("token=")[1].split()[0].strip()
    resp = await app_client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert resp.status_code == 200, resp.text

    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.json()["email_verified"] is True

    # single-use: reuse rejected
    resp = await app_client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert resp.status_code == 400


async def test_resend_verification_requires_auth(app_client, monkeypatch):
    import src.email.factory as factory

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    tokens = await register_user(app_client, "resend@example.com")
    sent.clear()
    resp = await app_client.post("/api/v1/auth/resend-verification", headers=auth_headers(tokens))
    assert resp.status_code == 202
    assert len(sent) == 1

    resp = await app_client.post("/api/v1/auth/resend-verification")
    assert resp.status_code == 401


async def test_forgot_reset_flow_end_to_end(app_client, monkeypatch):
    import src.email.factory as factory

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    tokens = await register_user(app_client, "reset@example.com")
    sent.clear()

    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "reset@example.com"}
    )
    assert resp.status_code == 202
    assert len(sent) == 1
    raw = sent[0].text_body.split("token=")[1].split()[0].strip()

    resp = await app_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw, "new_password": "NewPassword123!"},
    )
    assert resp.status_code == 200, resp.text

    # login works with the new password
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": "NewPassword123!"},
    )
    assert resp.status_code == 200, resp.text

    # Password recovery invalidates the session established before the reset.
    resp = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 401

    # single-use: reuse rejected
    resp = await app_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw, "new_password": "AnotherPass123!"},
    )
    assert resp.status_code == 400


async def test_forgot_unknown_email_still_202(app_client, monkeypatch):
    import src.email.factory as factory

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody@example.com"}
    )
    assert resp.status_code == 202
    assert sent == []


async def test_forgot_email_failure_still_202(app_client, monkeypatch):
    import src.email.factory as factory

    async def _send(_message):
        raise RuntimeError("email unavailable")

    monkeypatch.setattr(factory, "send_email", _send)
    await register_user(app_client, "email-failure@example.com")
    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "email-failure@example.com"}
    )
    assert resp.status_code == 202


async def test_reset_invalid_token_rejected(app_client):
    await register_user(app_client, "badtoken@example.com")
    resp = await app_client.post(
        "/api/v1/auth/reset-password",
        json={"token": "bogus", "new_password": "NewPassword123!"},
    )
    assert resp.status_code == 400


async def test_expired_reset_token_rejected(app_client, monkeypatch):
    from datetime import timedelta

    from sqlalchemy import select

    import src.email.factory as factory
    from src.core.dates import now_utc
    from src.core.security.tokens import OpaqueToken
    from src.db.session import SessionFactory
    from src.models.workspace import AuthToken, User

    async def _noop(message):
        return True

    monkeypatch.setattr(factory, "send_email", _noop)
    await register_user(app_client, "expired@example.com")
    async with SessionFactory() as session:
        user = (
            await session.execute(select(User).where(User.email == "expired@example.com"))
        ).scalar_one()
        raw = OpaqueToken.generate()
        session.add(
            AuthToken(
                user_id=user.id,
                purpose="password_reset",
                token_hash=OpaqueToken.hash(raw),
                expires_at=now_utc() - timedelta(minutes=1),
            )
        )
        await session.commit()
    resp = await app_client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw, "new_password": "NewPassword123!"},
    )
    assert resp.status_code == 400


async def test_login_not_blocked_when_unverified(app_client):
    # grace-period decision: unverified users can still log in
    tokens = await register_user(app_client, "grace@example.com")
    from tests.conftest import login

    login_tokens = await login(app_client, "grace@example.com")
    assert login_tokens["access_token"]
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(login_tokens))
    assert me.json()["email_verified"] is False
    _ = tokens


async def test_resend_verification_rate_limited(app_client, monkeypatch):
    """#1289: resend spends the auth-limiter budget per (IP, email)."""
    import src.email.factory as factory
    from src.settings import settings

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 2)
    tokens = await register_user(app_client, "resend-limit@example.com")
    sent.clear()
    headers = auth_headers(tokens)
    for _ in range(2):
        resp = await app_client.post("/api/v1/auth/resend-verification", headers=headers)
        assert resp.status_code == 202, resp.text
    assert len(sent) == 2
    resp = await app_client.post("/api/v1/auth/resend-verification", headers=headers)
    assert resp.status_code == 429, resp.text
    assert "Retry-After" in resp.headers
    assert len(sent) == 2  # throttled call sends nothing


async def test_resend_verification_key_reachable_but_rate_limited(app_client, monkeypatch):
    """#1289: the route stays key-reachable by design, but each send now spends
    the auth-limiter budget, so a key cannot trigger mail per call without
    bound. Quota is still uncharged — the route never reaches `record_key_use`.
    """
    import src.email.factory as factory
    from src.settings import settings

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 2)
    tokens = await register_user(app_client, "key-resend@example.com")
    ws = await create_workspace(app_client, tokens, "Resend Inc")
    owner_headers = ws_headers(tokens, ws["id"])

    resp = await app_client.post(
        "/api/v1/api-keys",
        json={"name": "resender", "permissions": ["notification:read"]},
        headers=owner_headers,
    )
    assert resp.status_code == 201, resp.text
    key = resp.json()
    key_headers = {"Authorization": f"Bearer {key['key']}", "X-Workspace-ID": ws["id"]}

    sent.clear()
    for _ in range(2):
        resp = await app_client.post("/api/v1/auth/resend-verification", headers=key_headers)
        assert resp.status_code == 202, resp.text
    assert len(sent) == 2
    resp = await app_client.post("/api/v1/auth/resend-verification", headers=key_headers)
    assert resp.status_code == 429, resp.text

    keys = await app_client.get("/api/v1/api-keys", headers=owner_headers)
    mine = next(k for k in keys.json() if k["id"] == key["id"])
    assert mine["usage_count"] == 0  # rate-limited, still not quota-charged


async def test_forgot_password_rate_limited(app_client, monkeypatch):
    """#1313: forgot-password spends the auth-limiter budget per (IP, email)."""
    import src.email.factory as factory
    from src.settings import settings

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 2)
    await register_user(app_client, "forgot-limit@example.com")
    sent.clear()
    for _ in range(2):
        resp = await app_client.post(
            "/api/v1/auth/forgot-password", json={"email": "forgot-limit@example.com"}
        )
        assert resp.status_code == 202, resp.text
    assert len(sent) == 2
    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "forgot-limit@example.com"}
    )
    assert resp.status_code == 429, resp.text
    assert "Retry-After" in resp.headers
    assert len(sent) == 2  # throttled call sends nothing


async def test_forgot_unknown_email_spends_budget(app_client, monkeypatch):
    """#1313: unknown addresses spend the same budget — no existence oracle."""
    import src.email.factory as factory
    from src.settings import settings

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 2)
    for _ in range(2):
        resp = await app_client.post(
            "/api/v1/auth/forgot-password", json={"email": "forgot-ghost@example.com"}
        )
        assert resp.status_code == 202, resp.text
    assert sent == []
    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "forgot-ghost@example.com"}
    )
    assert resp.status_code == 429, resp.text


async def test_forgot_password_budget_is_per_email(app_client, monkeypatch):
    """#1313: exhausting one email's budget leaves a sibling email under the
    same IP unthrottled."""
    import src.email.factory as factory
    from src.settings import settings

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 1)
    await register_user(app_client, "forgot-a@example.com")
    await register_user(app_client, "forgot-b@example.com")
    sent.clear()
    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "forgot-a@example.com"}
    )
    assert resp.status_code == 202, resp.text
    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "forgot-a@example.com"}
    )
    assert resp.status_code == 429, resp.text
    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "forgot-b@example.com"}
    )
    assert resp.status_code == 202, resp.text


# --- #1346: coarse per-IP cap on total auth mail volume ---


async def test_ip_mail_cap_bounds_total_mail_per_ip(app_client, monkeypatch):
    """#1346: each distinct known address has its own per-(IP, email) budget,
    but the IP-wide mail cap still gets 429 (all three calls share one IP,
    and unknown addresses never send mail, so the cap is pinned with
    registered recipients)."""
    import src.email.factory as factory
    from src.settings import settings

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    monkeypatch.setattr(settings, "auth_ip_mail_max_attempts", 4)
    await register_user(app_client, "ipmail-a@example.com")  # charge 1
    await register_user(app_client, "ipmail-b@example.com")  # charge 2
    sent.clear()
    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "ipmail-a@example.com"}
    )
    assert resp.status_code == 202, resp.text  # charge 3, send
    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "ipmail-b@example.com"}
    )
    assert resp.status_code == 202, resp.text  # charge 4, send
    assert len(sent) == 2
    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "ghost@example.com"}
    )
    assert resp.status_code == 429, resp.text
    assert "Retry-After" in resp.headers
    assert len(sent) == 2  # throttled call sends nothing


async def test_ip_mail_cap_counts_register(app_client, monkeypatch):
    """#1346: register's verification mail spends IP-mail budget, and no
    account row exists when the cap 429s (check runs before the DB write)."""
    import src.email.factory as factory
    from src.settings import settings

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    monkeypatch.setattr(settings, "auth_ip_mail_max_attempts", 1)
    tokens = await register_user(app_client, "capreg-a@example.com")
    assert tokens["access_token"]
    assert len(sent) == 1
    resp = await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "capreg-b@example.com",
            "password": "Password123!",
            "first_name": "C",
            "last_name": "B",
        },
    )
    assert resp.status_code == 429, resp.text
    assert len(sent) == 1
    # no account row exists: the 429 was raised before any DB write
    from sqlalchemy import select
    from src.db.session import SessionFactory
    from src.models.workspace import User

    async with SessionFactory() as session:
        uid = (
            await session.execute(
                select(User.id).where(User.email == "capreg-b@example.com")
            )
        ).scalar_one_or_none()
    assert uid is None


async def test_ip_mail_cap_aggregates_across_routes(app_client, monkeypatch):
    """#1346: register, forgot-password and resend-verification draw down one
    shared per-IP budget; the next call 429s."""
    import src.email.factory as factory
    from src.settings import settings

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    monkeypatch.setattr(settings, "auth_ip_mail_max_attempts", 3)
    tokens = await register_user(app_client, "agg-a@example.com")  # charge 1, send
    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "agg-a@example.com"}
    )  # charge 2, send
    assert resp.status_code == 202, resp.text
    resp = await app_client.post(
        "/api/v1/auth/resend-verification", headers=auth_headers(tokens)
    )  # charge 3, send
    assert resp.status_code == 202, resp.text
    resp = await app_client.post(
        "/api/v1/auth/forgot-password", json={"email": "agg-ghost@example.com"}
    )
    assert resp.status_code == 429, resp.text
    assert len(sent) == 3  # register + forgot + resend all send; unknown ghost sends none


async def test_ip_mail_cap_is_per_ip(app, monkeypatch):
    """#1346: two client IPs each keep their own mail budget under one app."""
    import src.email.factory as factory
    from src.settings import settings

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    monkeypatch.setattr(settings, "auth_ip_mail_max_attempts", 1)

    # one app instance, two transports with distinct client IPs
    from httpx import ASGITransport, AsyncClient

    one = AsyncClient(transport=ASGITransport(app=app, client=("10.0.0.1", 0)), base_url="http://test")
    two = AsyncClient(transport=ASGITransport(app=app, client=("10.0.0.2", 0)), base_url="http://test")
    try:
        resp = await one.post(
            "/api/v1/auth/register",
            json={
                "email": "ipea@example.com",
                "password": "Password123!",
                "first_name": "I",
                "last_name": "A",
            },
        )
        assert resp.status_code == 201, resp.text
        resp = await two.post(
            "/api/v1/auth/register",
            json={
                "email": "ipeb@example.com",
                "password": "Password123!",
                "first_name": "I",
                "last_name": "B",
            },
        )
        assert resp.status_code == 201, resp.text
        assert len(sent) == 2
    finally:
        await one.aclose()
        await two.aclose()


async def test_ip_mail_cap_skipped_on_register_conflict(app_client, monkeypatch):
    """#1346: a 409 duplicate registers no mail charge — only a send (or its
    attempt) is money."""
    import src.email.factory as factory
    from src.settings import settings

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    monkeypatch.setattr(settings, "auth_ip_mail_max_attempts", 2)
    body = {
        "email": "dup@example.com",
        "password": "Password123!",
        "first_name": "D",
        "last_name": "U",
    }
    resp = await app_client.post("/api/v1/auth/register", json=body)
    assert resp.status_code == 201
    resp = await app_client.post("/api/v1/auth/register", json=body)
    assert resp.status_code == 409, resp.text
    resp = await app_client.post(
        "/api/v1/auth/register",
        json={**body, "email": "dup-b@example.com"},
    )
    assert resp.status_code == 201, resp.text  # fits because 409 charged nothing
    resp = await app_client.post(
        "/api/v1/auth/register",
        json={**body, "email": "dup-c@example.com"},
    )
    assert resp.status_code == 429, resp.text
    assert len(sent) == 2


async def test_login_does_not_spend_ip_mail_budget(app_client, monkeypatch):
    """#1346: login sends no mail, so failed logins leave the IP-mail budget
    untouched for register."""
    import src.email.factory as factory
    from src.settings import settings

    sent = []

    async def _send(message):
        sent.append(message)
        return True

    monkeypatch.setattr(factory, "send_email", _send)
    monkeypatch.setattr(settings, "auth_ip_mail_max_attempts", 1)
    for _ in range(3):
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@example.com", "password": "WrongPass123!"},
        )
        assert resp.status_code in (401, 400), resp.text
    tokens = await register_user(app_client, "nomail@example.com")  # budget unspent
    assert tokens["access_token"]
    assert len(sent) == 1
