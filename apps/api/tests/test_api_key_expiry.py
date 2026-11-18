"""API key expiry: creation validation, auth rejection, and the cleanup job."""

import asyncio
import logging
import os
import shutil
import tempfile
import threading
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.dates import ensure_utc, now_utc
from src.db.base import Base
from src.db.embedded import _kill_postmaster, embedded_uri
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
    wait_for,
    wait_for_audit_action,
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


# The lock-and-recheck, observed on Postgres. SQLite serialises writers, so the
# `_RacingCtx` tests above reproduce the row state the UPDATE sees without the
# UPDATE ever blocking. Under READ COMMITTED, Postgres blocks an UPDATE on a
# concurrent transaction's row lock and re-evaluates the UPDATE's WHERE against
# the committed row version once that transaction commits — the mechanism the
# fix relies on, observable only here.


def _raw_dsn(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _postgres_reachable(url: str) -> bool:
    dsn = _raw_dsn(url)
    ok = False

    def _probe() -> None:
        nonlocal ok

        async def _ping() -> None:
            conn = await asyncpg.connect(dsn, timeout=5)
            try:
                await conn.execute("SELECT 1")
            finally:
                await conn.close()

        try:
            asyncio.run(_ping())
            ok = True
        except Exception:
            ok = False

    # Own thread: asyncio.run refuses to nest, and this runs beside async fixtures.
    thread = threading.Thread(target=_probe, daemon=True)
    thread.start()
    thread.join(timeout=10)
    return ok


@pytest.fixture(scope="module")
def postgres_url() -> str:
    """URL of a throwaway Postgres, or skip when none can be had.

    $TEST_POSTGRES_URL wins when set; otherwise the repo's embedded Postgres
    (the pgserver path `db-check.sh` uses) starts on a scratch directory, so
    the existing `api-test` CI job runs this without a database service. The
    fixture stops the scratch postmaster it started and removes the directory.
    """
    override = os.environ.get("TEST_POSTGRES_URL")
    if override:
        if not _postgres_reachable(override):
            pytest.skip(f"TEST_POSTGRES_URL is not reachable: {override}")
        yield override
        return

    scratch = Path(tempfile.mkdtemp(prefix="saas-apikey-recheck-pg-"))
    saved = os.environ.get("EMBEDDED_DB_DIR")
    os.environ["EMBEDDED_DB_DIR"] = str(scratch)
    try:
        url: str | None = None
        try:
            url = embedded_uri()
        except Exception as exc:  # pgserver missing or cannot start on this host
            pytest.skip(f"postgres unavailable: {exc}")
        try:
            yield url
        finally:
            # Ours to stop: fast-shutdown the scratch postmaster, then drop the dir.
            with suppress(Exception):
                _kill_postmaster()
            shutil.rmtree(scratch, ignore_errors=True)
    finally:
        os.environ.pop("EMBEDDED_DB_DIR", None)
        if saved is not None:
            os.environ["EMBEDDED_DB_DIR"] = saved


@pytest.fixture
async def pg_session_factory(postgres_url) -> async_sessionmaker[AsyncSession]:
    """All tables on the throwaway Postgres, dropped again afterwards.

    Models are the source of truth and render natively on Postgres
    (StringUUID, src/db/base.py), so create_all is safe; api_keys has no
    foreign keys, so the test below inserts minimal rows directly.
    """
    engine = create_async_engine(postgres_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    finally:
        await engine.dispose()


class _PostgresRacingCtx(_FakeCtx):
    """Job context over the throwaway Postgres that parks the job mid-run.

    The job's first SELECT runs, then the context waits on `proceed`. The test
    spends that window starting an *uncommitted* revoke on a second connection
    — the interleaving under which the job's UPDATE blocks on the row lock and
    Postgres re-evaluates its WHERE once the revoker commits. `_RacingCtx`
    reproduces the same row state on the job's own session; only this one can
    exercise the database's recheck.
    """

    def __init__(self, factory, bus=None) -> None:
        super().__init__(bus)
        self._factory = factory
        self.select_done = asyncio.Event()
        self.proceed = asyncio.Event()
        self.backend_pid: int | None = None
        self._gated = True
        self._session = None

    def session(self):
        return self

    async def __aenter__(self):
        self._session = self._factory()
        await self._session.__aenter__()
        self.backend_pid = (
            await self._session.execute(text("select pg_backend_pid()"))
        ).scalar_one()
        return self

    async def __aexit__(self, *exc_info):
        return await self._session.__aexit__(*exc_info)

    async def execute(self, stmt, *args, **kwargs):
        if self._gated:
            self._gated = False
            result = await self._session.execute(stmt, *args, **kwargs)
            self.select_done.set()
            await self.proceed.wait()
            return result
        return await self._session.execute(stmt, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


async def _wait_for_blocked_pid(dsn: str, pid: int, timeout_s: float = 10.0) -> bool:
    """Poll until another backend is blocking `pid`'s current statement.

    True only once the job's UPDATE is parked on the revoker's row lock — the
    state the recheck fires from. False on timeout, which the test turns into
    a loud failure instead of a silent pass through the weaker scan-time path.
    """
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        return await wait_for(
            lambda: conn.fetchval("select pg_blocking_pids($1)", pid),
            timeout_secs=timeout_s,
            interval=0.05,
        )
    finally:
        await conn.close()


async def test_cleanup_job_recheck_survives_a_committed_concurrent_revoke(
    pg_session_factory, postgres_url, monkeypatch, caplog
):
    """Postgres only: the UPDATE survives the revoke via lock-then-recheck.

    The revoking transaction stays open while the job's UPDATE runs: the UPDATE
    blocks on the raced row's lock, the revoker commits, and READ COMMITTED
    re-evaluates `revoked_at IS NULL` against the committed row version and
    skips the key. That pins the mechanism the re-asserted predicate exists
    for, which no SQLite test can reach — its UPDATE never blocks.
    """
    monkeypatch.setattr(settings, "api_key_retention_days", 0)

    async with pg_session_factory() as session:
        isolation = (await session.execute(text("show transaction_isolation"))).scalar_one()
    assert isolation == "read committed", (
        f"the recheck is a READ COMMITTED behaviour, suite saw {isolation}"
    )

    now = now_utc()
    workspace_id = str(uuid.uuid4())
    creator_id = str(uuid.uuid4())
    raced = ApiKey(
        workspace_id=workspace_id,
        name="raced",
        key_prefix="sk-raced",
        key_hash=f"recheck-raced-{uuid.uuid4()}",
        created_by_user_id=creator_id,
        expires_at=now - timedelta(days=1),
    )
    clean = ApiKey(
        workspace_id=workspace_id,
        name="clean",
        key_prefix="sk-clean",
        key_hash=f"recheck-clean-{uuid.uuid4()}",
        created_by_user_id=creator_id,
        expires_at=now - timedelta(days=1),
    )
    async with pg_session_factory() as session:
        session.add_all([raced, clean])
        await session.commit()

    user_revoked_at = now - timedelta(minutes=5)
    bus = RecordingBus()
    ctx = _PostgresRacingCtx(pg_session_factory, bus)
    job = asyncio.create_task(api_key_cleanup(ctx))
    try:
        await asyncio.wait_for(ctx.select_done.wait(), timeout=10)

        # The revoking transaction holds the row lock across the job's blocked
        # UPDATE: committing before the UPDATE starts would only re-filter the
        # row at scan time — the weaker path the sqlite tests already cover.
        async with pg_session_factory() as revoker:
            await revoker.execute(
                update(ApiKey)
                .where(ApiKey.id == raced.id, ApiKey.revoked_at.is_(None))
                .values(revoked_at=user_revoked_at)
            )
            ctx.proceed.set()

            blocked = await _wait_for_blocked_pid(_raw_dsn(postgres_url), ctx.backend_pid)
            assert blocked, (
                "the job's UPDATE never blocked on the uncommitted revoke — the "
                "statement shape changed (e.g. NOWAIT / SKIP LOCKED / FOR UPDATE) or "
                "the revoke lost the race for the row lock"
            )
            await revoker.commit()

        with caplog.at_level(logging.INFO, logger="src.jobs.builtin"):
            await asyncio.wait_for(job, timeout=30)
    finally:
        if not job.done():
            job.cancel()
            with suppress(asyncio.CancelledError):
                await job

    async with pg_session_factory() as session:
        row = await session.get(ApiKey, raced.id)
        assert ensure_utc(row.revoked_at) == ensure_utc(user_revoked_at)
        assert (await session.get(ApiKey, clean.id)).revoked_at is not None

    # The raced key was selected but not written, so it gets no event and no audit entry.
    assert [p["apikey_id"] for p, _, _ in bus.by_subject(Subjects.APIKEY_REVOKED)] == [clean.id]
    assert [p["resource_id"] for p, _, _ in bus.audit()] == [clean.id]
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
    # Counting ids does not pin the separator. The prose above already contains ", ",
    # so pin the list itself: a quote-glued separator fails both assertions.
    assert ", " in message.split("of them: ", 1)[1]
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
    assert [r.levelno for r in records] == [logging.ERROR, logging.WARNING, logging.WARNING]


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
        assert definition.enabled is True, "apikeys.cleanup is not enabled"
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
    await wait_for_audit_action(ws["id"], "apikey.revoked", timeout_secs=10.0)
    async with SessionFactory() as session:
        audited = (
            (
                await session.execute(
                    select(AuditLogEntry)
                    .where(
                        AuditLogEntry.resource_id == expired["id"],
                        AuditLogEntry.action == "apikey.revoked",
                    )
                    .order_by(AuditLogEntry.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
    assert audited is not None, f"no apikey.revoked audit entry for {expired['id']}"
    assert audited.details.get("reason") == "expired"
