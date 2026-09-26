"""API key expiry: creation validation, auth rejection, and the cleanup job."""

from datetime import timedelta

from src.core.dates import now_utc
from src.db.session import SessionFactory
from src.jobs.builtin import api_key_cleanup
from src.jobs.registry import job_registry
from src.models.api_key import ApiKey
from tests.conftest import create_workspace, register_user, ws_headers


async def _create_key(client, headers, *, name="expiring", body=None):
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": name, "permissions": ["member:read"], **(body or {})},
        headers=headers,
    )
    return resp


async def test_key_with_future_expiry_authenticates(app_client):
    client = app_client
    owner = await register_user(client, "quinn@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    expires = now_utc() + timedelta(days=7)
    resp = await _create_key(client, headers, body={"expires_at": expires.isoformat()})
    assert resp.status_code == 201, resp.text
    key = resp.json()
    assert key["expires_at"] is not None

    key_headers = {"Authorization": f"Bearer {key['key']}", "X-Workspace-ID": ws["id"]}
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200

    # the list echoes the expiry and accepts it as a sort field
    items = (await client.get("/api/v1/api-keys", headers=headers)).json()
    assert next(k for k in items if k["id"] == key["id"])["expires_at"] is not None
    resp = await client.get("/api/v1/api-keys?sort[]=expires_at", headers=headers)
    assert resp.status_code == 200


async def test_create_rejects_past_and_naive_expiry(app_client):
    client = app_client
    owner = await register_user(client, "rosa@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    # A key born expired is a mistake — refuse it at create time.
    past = (now_utc() - timedelta(days=1)).isoformat()
    resp = await _create_key(client, headers, body={"expires_at": past})
    assert resp.status_code == 422
    assert "future" in resp.json()["detail"]

    # A naive datetime has no offset, so the instant is ambiguous.
    resp = await _create_key(client, headers, body={"expires_at": "2027-01-01T00:00:00"})
    assert resp.status_code == 422


async def test_expired_key_is_rejected_before_the_job_runs(app_client):
    client = app_client
    owner = await register_user(client, "sybil@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    key = (
        await _create_key(
            client, headers, body={"expires_at": (now_utc() + timedelta(hours=1)).isoformat()}
        )
    ).json()
    key_headers = {"Authorization": f"Bearer {key['key']}", "X-Workspace-ID": ws["id"]}
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200

    async with SessionFactory() as session:
        row = await session.get(ApiKey, key["id"])
        row.expires_at = now_utc() - timedelta(seconds=1)
        await session.commit()

    # Expired keys fail auth on the expiry check alone — no job, no revoke.
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 401
    async with SessionFactory() as session:
        row = await session.get(ApiKey, key["id"])
        assert row.revoked_at is None


async def test_key_without_expiry_is_unaffected(app_client):
    client = app_client
    owner = await register_user(client, "vera@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    key = (await _create_key(client, headers)).json()
    assert key["expires_at"] is None

    key_headers = {"Authorization": f"Bearer {key['key']}", "X-Workspace-ID": ws["id"]}
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200


async def test_cleanup_job_revokes_expired_and_deletes_aged(app_client):
    """The job mirrors what auth already enforces: revoke expired, purge old."""
    client = app_client
    owner = await register_user(client, "wendy@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    now = now_utc()
    # active and already expired -> revoked by the job
    expired = (await _create_key(client, headers, name="expired")).json()
    # revoked long ago -> hard-deleted
    aged = (await _create_key(client, headers, name="aged")).json()
    # live, no expiry -> untouched
    live = (await _create_key(client, headers, name="live")).json()

    async with SessionFactory() as session:
        rows = {}
        for key_id, expires_at, revoked_at in (
            (expired["id"], now - timedelta(days=2), None),
            (aged["id"], None, now - timedelta(days=40)),
            (live["id"], None, None),
        ):
            row = await session.get(ApiKey, key_id)
            row.expires_at = expires_at
            row.revoked_at = revoked_at
            rows[key_id] = row.id
        await session.commit()

    await api_key_cleanup(_FakeCtx())

    async with SessionFactory() as session:
        # expired key now revoked
        assert (await session.get(ApiKey, expired["id"])).revoked_at is not None
        # aged key gone
        assert await session.get(ApiKey, aged["id"]) is None
        # live key untouched
        row = await session.get(ApiKey, live["id"])
        assert row.revoked_at is None
        assert row.expires_at is None


class _FakeCtx:
    """Minimal JobContext stand-in: the handler only needs a session()."""

    def session(self):
        return SessionFactory()


def test_job_is_registered_as_a_global_daily_job():
    spec = job_registry.get("apikeys.cleanup")
    assert spec is not None
    assert spec.scope == "global"
    assert spec.default_enabled is True
