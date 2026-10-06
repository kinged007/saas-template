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
