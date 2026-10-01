"""API key expiry: creation validation, auth rejection, and the cleanup job."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

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


class _RacingCtx(_FakeCtx):
    """Job context whose session revokes the key the moment the job's SELECT returns.

    The revoke runs on the job's own session, so the two statements share one
    transaction — no thread, no lock contention, and the interleaving is exact.
    """

    def __init__(self, bus, key_id, revoked_at) -> None:
        super().__init__(bus)
        self._key_id = key_id
        self._revoked_at = revoked_at
        self._raced = False
        self._session = None

    def session(self):
        return self

    async def __aenter__(self):
        self._session = SessionFactory()
        await self._session.__aenter__()
        return self

    async def __aexit__(self, *exc_info):
        return await self._session.__aexit__(*exc_info)

    async def execute(self, stmt, *args, **kwargs):
        result = await self._session.execute(stmt, *args, **kwargs)
        if not self._raced and stmt.is_select:
            self._raced = True
            await self._session.execute(
                update(ApiKey)
                .where(ApiKey.id == self._key_id, ApiKey.revoked_at.is_(None))
                .values(revoked_at=self._revoked_at)
            )
        return result

    def __getattr__(self, name):
        return getattr(self._session, name)


class _FailingBus(RecordingBus):
    """Fails every publish for the second distinct key, or for every key if `fail_all`."""

    def __init__(self, *, fail_all: bool = False) -> None:
        super().__init__()
        self._seen = []
        self._fail_all = fail_all
        self.fail_on = None

    async def publish(
        self,
        subject: str,
        payload: dict,
        *,
        correlation_id: str | None = None,
        transient: bool = False,
    ) -> None:
        key_id = payload.get("apikey_id")
        if key_id is not None:
            if key_id not in self._seen:
                self._seen.append(key_id)
                if len(self._seen) == 2:
                    self.fail_on = key_id
            if key_id == self.fail_on or self._fail_all:
                raise RuntimeError("nats unavailable")
        await super().publish(subject, payload, correlation_id=correlation_id, transient=transient)


async def _backdated_key(client, headers, name: str) -> dict:
    """Create a key through the API, then back-date it: the API rejects a past expiry."""
    resp = await client.post(
        "/api/v1/api-keys",
        json={
            "name": name,
            "permissions": ["member:read"],
            "expires_at": (now_utc() + timedelta(days=1)).isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    key = resp.json()
    async with SessionFactory() as session:
        row = await session.get(ApiKey, key["id"])
        row.expires_at = now_utc() - timedelta(days=1)
        await session.commit()
    return key


async def test_cleanup_job_keeps_a_revocation_raced_inside_the_run(app_client, monkeypatch):
    """A user revoke landing between the SELECT and the UPDATE must not be overwritten."""
    monkeypatch.setattr(settings, "api_key_retention_days", 0)
    client = app_client
    owner = await register_user(client, "racer@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    expired = await _backdated_key(client, headers, "raced")

    user_revoked_at = now_utc() - timedelta(minutes=5)
    bus = RecordingBus()
    await api_key_cleanup(_RacingCtx(bus, expired["id"], user_revoked_at))

    async with SessionFactory() as session:
        row = await session.get(ApiKey, expired["id"])
        # The user's timestamp survives, so the 30-day retention clock keeps running
        # from the revocation they actually performed.
        assert ensure_utc(row.revoked_at) == ensure_utc(user_revoked_at)
    # The job did not revoke it, so it claims nothing about who did.
    assert bus.by_subject(Subjects.APIKEY_REVOKED) == []
    assert bus.audit() == []


async def test_cleanup_job_reports_only_the_keys_it_actually_revoked(
    app_client, monkeypatch, caplog
):
    """One raced and one clean key: the summary counts the write, not the read."""
    monkeypatch.setattr(settings, "api_key_retention_days", 0)
    client = app_client
    owner = await register_user(client, "mixed@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    raced = await _backdated_key(client, headers, "raced")
    clean = await _backdated_key(client, headers, "clean")

    user_revoked_at = now_utc() - timedelta(minutes=5)
    bus = RecordingBus()
    with caplog.at_level(logging.INFO, logger="src.jobs.builtin"):
        await api_key_cleanup(_RacingCtx(bus, raced["id"], user_revoked_at))

    async with SessionFactory() as session:
        assert ensure_utc((await session.get(ApiKey, raced["id"])).revoked_at) == ensure_utc(
            user_revoked_at
        )
        assert (await session.get(ApiKey, clean["id"])).revoked_at is not None

    # The raced key was selected but not written, so it gets no event and no audit entry.
    assert [p["apikey_id"] for p, _, _ in bus.by_subject(Subjects.APIKEY_REVOKED)] == [clean["id"]]
    assert [p["resource_id"] for p, _, _ in bus.audit()] == [clean["id"]]
    assert "1 key(s) revoked as expired" in caplog.text


async def test_cleanup_job_publishes_every_other_key_when_one_publish_fails(
    app_client, monkeypatch
):
    """One key's publish failure costs that key its audit entry, not the next keys'."""
    monkeypatch.setattr(settings, "api_key_retention_days", 0)
    client = app_client
    owner = await register_user(client, "publisher@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    keys = [await _backdated_key(client, headers, f"key {n}") for n in range(3)]

    bus = _FailingBus()
    with pytest.raises(RuntimeError) as excinfo:
        await api_key_cleanup(_FakeCtx(bus))

    failing = bus.fail_on
    published = sorted(k["id"] for k in keys if k["id"] != failing)

    # The commit is not transactional with the bus, so every key stays revoked even
    # though the failing one never got its event or its audit entry.
    async with SessionFactory() as session:
        for key in keys:
            row = await session.get(ApiKey, key["id"])
            assert row is not None
            assert row.revoked_at is not None

    # The keys after the failing one are published as usual — the loop keeps going.
    assert (
        sorted(p["apikey_id"] for p, _, _ in bus.by_subject(Subjects.APIKEY_REVOKED)) == published
    )
    assert sorted(p["resource_id"] for p, _, _ in bus.audit()) == published

    # The run fails once, naming what was lost.
    message = str(excinfo.value)
    assert "3 key(s) revoked" in message
    assert failing in message


async def test_cleanup_job_error_message_caps_the_id_list(app_client, monkeypatch):
    """job_runs.error is unbounded Text: a bus outage must not write one id per key."""
    monkeypatch.setattr(settings, "api_key_retention_days", 0)
    client = app_client
    owner = await register_user(client, "outage@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    keys = [await _backdated_key(client, headers, f"key {n}") for n in range(12)]

    with pytest.raises(RuntimeError) as excinfo:
        await api_key_cleanup(_FakeCtx(_FailingBus(fail_all=True)))

    message = str(excinfo.value)
    assert "12 key(s) revoked" in message
    assert "for 12 of them" in message
    # 10 ids listed by name, the remaining 2 only counted.
    assert sum(1 for key in keys if key["id"] in message) == 10
    assert "(+2 more)" in message
    # Counting ids does not pin the separator: this asserts the joined form, so a
    # quote-glued list fails here instead of reading as a quoting bug to an operator.
    assert ", " in message
    assert "'" not in message


async def test_cleanup_job_logs_only_the_first_publish_failure_with_a_traceback(
    app_client, monkeypatch, caplog
):
    """One traceback per key would flood the log during a bus outage; only the
    first failure carries one, because nothing retries a FAILED run and that
    record is the only account of why the publish failed."""
    monkeypatch.setattr(settings, "api_key_retention_days", 0)
    client = app_client
    owner = await register_user(client, "logsplit@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    for n in range(3):
        await _backdated_key(client, headers, f"key {n}")

    with caplog.at_level(logging.INFO, logger="src.jobs.builtin"):
        with pytest.raises(RuntimeError):
            await api_key_cleanup(_FakeCtx(_FailingBus(fail_all=True)))

    records = [r for r in caplog.records if "audit publish failed" in r.getMessage()]
    assert len(records) == 3
    assert records[0].exc_info is not None
    assert [r.exc_info for r in records[1:]] == [None, None]


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
