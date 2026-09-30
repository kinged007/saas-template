from datetime import timedelta

from src.core.dates import now_utc
from tests.conftest import auth_headers, login, register_user


async def test_revoked_session_access_token_rejected(app_client):
    client = app_client
    t1 = await register_user(client, "revoked-at@example.com")
    t2 = await login(client, "revoked-at@example.com")
    h1, h2 = auth_headers(t1), auth_headers(t2)

    resp = await client.get("/api/v1/auth/me", headers=h1)
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/auth/sessions", headers=h2)
    assert resp.status_code == 200, resp.text
    other = next(s for s in resp.json() if not s["current"])
    resp = await client.delete(f"/api/v1/auth/sessions/{other['id']}", headers=h2)
    assert resp.status_code == 204, resp.text

    resp = await client.get("/api/v1/auth/me", headers=h1)
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "session revoked"
    # the surviving session keeps working — t1 died by user action, not rotation,
    # so replaying it is a stale cookie and must not arm the compromise path
    resp = await client.get("/api/v1/auth/me", headers=h2)
    assert resp.status_code == 200, resp.text
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert resp.status_code == 401, resp.text


async def test_session_routes_reject_api_key_callers(app_client):
    from tests.conftest import create_workspace

    client = app_client
    tokens = await register_user(client, "sesskey@example.com")
    workspace = await create_workspace(client, tokens)
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "k", "permissions": ["*"]},
        headers={**auth_headers(tokens), "X-Workspace-ID": workspace["id"]},
    )
    assert resp.status_code == 201, resp.text
    key_headers = {
        "Authorization": f"Bearer {resp.json()['key']}",
        "X-Workspace-ID": workspace["id"],
    }
    resp = await client.get("/api/v1/auth/sessions", headers=key_headers)
    assert resp.status_code == 403, resp.text
    resp = await client.delete("/api/v1/auth/sessions", headers=key_headers)
    assert resp.status_code == 403, resp.text
    resp = await client.delete("/api/v1/auth/sessions/anything", headers=key_headers)
    assert resp.status_code == 403, resp.text


async def test_reused_refresh_token_revokes_all_sessions(app_client):
    client = app_client
    t1 = await register_user(client, "reuse@example.com")
    t2 = await login(client, "reuse@example.com")

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert resp.status_code == 200, resp.text
    rotated = resp.json()

    # replaying an already-rotated token is a compromise signal
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "invalid refresh token"

    # every live session of that user is revoked
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert resp.status_code == 401, resp.text
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert resp.status_code == 401, resp.text
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(rotated))
    assert resp.status_code == 401, resp.text


async def test_unknown_refresh_token_revokes_nothing(app_client):
    client = app_client
    t1 = await register_user(client, "unknown@example.com")
    t2 = await login(client, "unknown@example.com")

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert resp.status_code == 401, resp.text

    resp = await client.get("/api/v1/auth/me", headers=auth_headers(t1))
    assert resp.status_code == 200, resp.text
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert resp.status_code == 200, resp.text


async def test_reused_refresh_token_does_not_lock_the_account(app_client):
    client = app_client
    t1 = await register_user(client, "reuse-login@example.com")
    t2 = await login(client, "reuse-login@example.com")

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert resp.status_code == 200, resp.text
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert resp.status_code == 401, resp.text

    # signed out, not disabled
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(t1))
    assert resp.status_code == 401, resp.text
    t3 = await login(client, "reuse-login@example.com")
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(t3))
    assert resp.status_code == 200, resp.text


async def test_revoke_all_sessions(app_client):
    client = app_client
    t1 = await register_user(client, "all@example.com")
    t2 = await login(client, "all@example.com")
    headers = auth_headers(t2)
    resp = await client.get("/api/v1/auth/sessions", headers=headers)
    assert resp.status_code == 200, resp.text
    listed = resp.json()
    assert len(listed) == 2
    assert sum(s["current"] for s in listed) == 1
    # revoking the current session alone is refused
    current = next(s for s in listed if s["current"])
    resp = await client.delete(f"/api/v1/auth/sessions/{current['id']}", headers=headers)
    assert resp.status_code == 400, resp.text
    resp = await client.delete("/api/v1/auth/sessions", headers=headers)
    assert resp.status_code == 204
    # the revoked session's access token 401s on the next request
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(t1))
    assert resp.status_code == 401, resp.text
    # the calling session survives
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert resp.status_code == 200, resp.text
    rotated = resp.json()
    resp = await client.get("/api/v1/auth/sessions", headers=auth_headers(rotated))
    remaining = resp.json()
    assert len(remaining) == 1
    assert remaining[0]["current"] is True
    # t1 was revoked by the user, not by a rotation: stale cookie, not a replay.
    # t2's live session is untouched.
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert resp.status_code == 401
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert resp.status_code == 200, resp.text


async def test_concurrent_refresh_of_one_token_is_deterministic(app_client):
    """Two racing rotations of one token never lock the user out.

    The SPA serialises this with the Web Locks API (see providers/refreshLock.ts),
    so the server only sees it from a client that does not. How many of the two
    requests win depends on the storage engine — ``with_for_update()`` is a real
    row lock on Postgres and a no-op on the in-memory sqlite the suite runs on —
    so the invariant asserted here is the one that holds either way: nobody
    beyond the rotation is disabled, and a fresh login always works.
    """
    import asyncio

    client = app_client
    await register_user(client, "race@example.com")
    t2 = await login(client, "race@example.com")

    first, second = await asyncio.gather(
        client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]}),
        client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]}),
    )
    assert first.status_code in (200, 401), first.text
    assert second.status_code in (200, 401), second.text
    for resp in (first, second):
        if resp.status_code == 401:
            assert resp.json()["detail"] == "invalid refresh token"

    # signed out at worst, never disabled: the user can always get back in
    t3 = await login(client, "race@example.com")
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(t3))
    assert resp.status_code == 200, resp.text


async def test_expired_rotated_token_does_not_revoke_sessions(app_client):
    """A rotated row that has since expired is dead, not stolen — expiry wins."""
    from sqlalchemy import select

    from src.core.security.tokens import OpaqueToken
    from src.db.session import SessionFactory
    from src.models.workspace import RefreshToken

    client = app_client
    await register_user(client, "expired-rotate@example.com")
    keep = await login(client, "expired-rotate@example.com")
    stale = await login(client, "expired-rotate@example.com")

    rotated = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": stale["refresh_token"]}
    )
    assert rotated.status_code == 200, rotated.text

    async with SessionFactory() as session:
        row = (
            await session.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hash == OpaqueToken.hash(stale["refresh_token"])
                )
            )
        ).scalar_one()
        assert row.revoke_reason == "rotated"
        row.expires_at = now_utc() - timedelta(minutes=1)
        await session.commit()

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": stale["refresh_token"]})
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "refresh token expired"

    # the untouched session is still live: an expired replay revoked nothing
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": keep["refresh_token"]})
    assert resp.status_code == 200, resp.text
