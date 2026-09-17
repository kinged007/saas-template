"""Password recovery + email verification (issue #12)."""

from tests.conftest import auth_headers, register_user


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
