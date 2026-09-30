"""API key expiry: creation validation, auth rejection, and the cleanup job."""

import asyncio
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select

from src.core.dates import ensure_utc, now_utc
from src.db.session import SessionFactory
from src.events.subjects import Subjects
from src.jobs.builtin import api_key_cleanup
from src.models.api_key import ApiKey
from src.models.audit import AuditLogEntry
from src.models.jobs import JobDefinition
from src.settings import settings
from tests.bus_doubles import RecordingBus
from tests.conftest import (
    create_workspace,
    register_user,
    run_job_via_scheduler,
    ws_headers,
)


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


async def test_non_utc_offset_expiry_stores_the_requested_instant(app_client):
    """The key must expire at the instant the caller named, not 9 hours later.

    SQLite's DateTime drops the offset on write, so an unnormalized aware
    datetime lands as its local wall clock and `authenticate` reads it back
    as UTC — the key would outlive its stated expiry by the offset.
    """
    client = app_client
    owner = await register_user(client, "naomi@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    # 2027-01-01T14:00+09:00 is the same instant as 2027-01-01T05:00Z.
    resp = await _create_key(client, headers, body={"expires_at": "2027-01-01T14:00:00+09:00"})
    assert resp.status_code == 201, resp.text
    requested = datetime(2027, 1, 1, 5, 0, tzinfo=UTC)

    key = resp.json()
    assert key["expires_at"] == requested.isoformat()

    async with SessionFactory() as session:
        row = await session.get(ApiKey, key["id"])
        assert ensure_utc(row.expires_at) == requested


async def test_expiry_accepts_any_offset(app_client):
    """Any offset lands on the same stored instant, so the API stays honest."""
    client = app_client
    owner = await register_user(client, "nadia@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    instant = now_utc() + timedelta(days=30)
    resp = await _create_key(
        client,
        headers,
        body={"expires_at": instant.astimezone(timezone(timedelta(hours=-5))).isoformat()},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["expires_at"] == instant.isoformat()


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

    bus = RecordingBus()
    await api_key_cleanup(_FakeCtx(bus))

    async with SessionFactory() as session:
        # expired key now revoked
        assert (await session.get(ApiKey, expired["id"])).revoked_at is not None
        # aged key gone
        assert await session.get(ApiKey, aged["id"]) is None
        # live key untouched
        row = await session.get(ApiKey, live["id"])
        assert row.revoked_at is None
        assert row.expires_at is None

    # Automated revocations leave the same audit trail a manual revoke does.
    assert [p["apikey_id"] for p, _, _ in bus.by_subject(Subjects.APIKEY_REVOKED)] == [
        expired["id"]
    ]
    assert [
        (a["action"], a["resource_id"], a["details"]["reason"], a["actor_user_id"])
        for a, _, _ in bus.audit()
    ] == [("apikey.revoked", expired["id"], "expired", None)]


async def test_cleanup_job_keeps_aged_keys_when_retention_is_disabled(app_client, monkeypatch):
    """api_key_retention_days=0 is a supported mode: revoke, never delete."""
    monkeypatch.setattr(settings, "api_key_retention_days", 0)
    client = app_client
    owner = await register_user(client, "nina@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    aged = (await _create_key(client, headers, name="aged")).json()
    async with SessionFactory() as session:
        row = await session.get(ApiKey, aged["id"])
        row.revoked_at = now_utc() - timedelta(days=400)
        await session.commit()

    await api_key_cleanup(_FakeCtx())

    async with SessionFactory() as session:
        assert await session.get(ApiKey, aged["id"]) is not None


class _FakeCtx:
    """Minimal JobContext stand-in: the handler only needs a session()."""

    def __init__(self, bus=None) -> None:
        self.bus = bus

    def session(self):
        return SessionFactory()


async def test_job_is_dispatched_by_the_scheduler(app_client):
    """Production wiring: the provisioned global job runs on the daily
    schedule, is claimed by a scheduler tick, and reaches its handler with the
    app's real bus — none of which `_FakeCtx` can observe."""
    client = app_client
    owner = await register_user(client, "odette@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    async with SessionFactory() as session:
        definition = (
            await session.execute(
                select(JobDefinition).where(
                    JobDefinition.key == "apikeys.cleanup",
                    JobDefinition.workspace_id.is_(None),
                )
            )
        ).scalar_one()
        assert definition.enabled is True
        assert definition.cron_schedule == "0 5 * * *"
        assert definition.missed_policy == "single"

    expired = (await _create_key(client, headers, name="expired")).json()
    async with SessionFactory() as session:
        row = await session.get(ApiKey, expired["id"])
        row.expires_at = now_utc() - timedelta(days=2)
        await session.commit()

    run, messages = await run_job_via_scheduler("apikeys.cleanup")
    assert run.trigger == "scheduled"
    assert run.status == "success", run.error
    assert any("api key cleanup — 1 key(s) revoked as expired" in m for m in messages), messages

    async with SessionFactory() as session:
        assert (await session.get(ApiKey, expired["id"])).revoked_at is not None

    # `publish_audit` no-ops without a bus, so this row exists only if the
    # executor really passed the app's bus to the handler.
    audited = await _wait_for_audit(expired["id"])
    assert audited.details.get("reason") == "expired"


async def _wait_for_audit(resource_id: str, timeout_s: float = 10.0):
    """The audit consumer is a background handler — poll for its row."""
    for _ in range(int(timeout_s * 10)):
        async with SessionFactory() as session:
            entry = (
                await session.execute(
                    select(AuditLogEntry).where(
                        AuditLogEntry.resource_id == resource_id,
                        AuditLogEntry.action == "apikey.revoked",
                    )
                )
            ).scalar_one_or_none()
            if entry is not None:
                return entry
        await asyncio.sleep(0.1)
    raise AssertionError(f"no apikey.revoked audit entry for {resource_id}")
