"""Battle-tested atomicity tests for the job manager.

These tests simulate production conditions: multiple uvicorn workers
(NATS JetStream workqueue) and dev multi-worker scenarios, all hitting
the same DB concurrently. Every test asserts that a scheduled occurrence
is executed EXACTLY ONCE — critical when jobs cost money.

Two atomicity barriers are under test:
1. Scheduler CAS: UPDATE job_definitions SET next_run_at=:new WHERE id=:id AND next_run_at=:old
2. Executor CAS: UPDATE job_runs SET status='running' WHERE id=:id AND status='pending'

Both must hold under high concurrency on SQLite (dev) and Postgres (prod).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select

from src.core.dates import now_utc
from src.db.session import SessionFactory
from src.jobs.registry import JobSpec, job_registry
from src.models.jobs import JobDefinition, JobLogEntry, JobRun, JobRunStatus
from src.services.jobs import JobService
from tests.test_jobs import _by_key, setup_workspace

# ---------------------------------------------------------------------------
# Battle job that simulates a money-cost operation.
# It increments a DB-backed counter and sleeps to widen the race window.
# ---------------------------------------------------------------------------

battle_counts: dict[str, int] = {}
battle_lock = asyncio.Lock()


# Use a dedicated in-memory counter keyed by run_id to detect double execution
# without relying on external state. The handler deliberately holds the event
# loop for 150ms to maximize overlap between concurrent claimants.
@job_registry.register(
    JobSpec(
        key="test.battle_money",
        name="Battle Money Job",
        description="Simulates a money-cost job; must run exactly once per occurrence.",
        scope="workspace",
        schedule="0 * * * *",
        params_schema={},
        default_enabled=False,
        missed_policy="single",
        timeout_seconds=30,
    )
)
async def _battle_money(ctx) -> None:  # type: ignore[no-redef]
    # Widen race window
    await asyncio.sleep(0.15)
    async with battle_lock:
        battle_counts[ctx.run_id] = battle_counts.get(ctx.run_id, 0) + 1
    # Also write a log line so we can assert via DB even if in-memory state is reset
    print(f"[BATTLE] money job executed run={ctx.run_id[:8]} count={battle_counts[ctx.run_id]}")
    import logging

    logging.getLogger("test.battle").info("money job run %s", ctx.run_id[:8])


@job_registry.register(
    JobSpec(
        key="test.battle_fast",
        name="Battle Fast Job",
        description="Fast battle job for scheduler-only tests.",
        scope="workspace",
        schedule="* * * * *",
        params_schema={},
        default_enabled=False,
        missed_policy="single",
        timeout_seconds=30,
    )
)
async def _battle_fast(ctx) -> None:  # type: ignore[no-redef]
    async with battle_lock:
        battle_counts[ctx.run_id] = battle_counts.get(ctx.run_id, 0) + 1
    print(f"[BATTLE-FAST] run={ctx.run_id[:8]}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_due_job(client, headers, key="test.battle_money") -> str:
    """Return definition_id for a due, enabled job."""
    jobs = (await client.get("/api/v1/jobs", headers=headers)).json()
    job = _by_key(jobs, key)
    # Force it due 5s ago
    async with SessionFactory() as session:
        definition = await session.get(JobDefinition, job["id"])
        definition.enabled = True
        definition.next_run_at = now_utc() - timedelta(seconds=5)
        await session.commit()
    return job["id"]


async def _count_runs(definition_id: str) -> int:
    async with SessionFactory() as session:
        rows = (
            (await session.execute(select(JobRun).where(JobRun.definition_id == definition_id)))
            .scalars()
            .all()
        )
        return len(rows)


async def _concurrent_schedule_due(concurrency: int) -> list[int]:
    """Launch `concurrency` schedulers with isolated sessions (simulates N workers)."""

    async def _worker():
        async with SessionFactory() as session:
            return await JobService(session).schedule_due()

    results = await asyncio.gather(*[_worker() for _ in range(concurrency)])
    return list(results)


async def _concurrent_execute(run_id: str, concurrency: int) -> None:
    """Launch `concurrency` executors for the same pending run."""

    from src.jobs.executor import execute_run

    await asyncio.gather(*[execute_run(run_id) for _ in range(concurrency)])


# ---------------------------------------------------------------------------
# 1. Scheduler atomicity — the critical money barrier
# ---------------------------------------------------------------------------


async def test_battle_concurrent_schedulers_single_due_job_creates_exactly_one_run(
    app_client,
):
    """50 workers race to schedule the same due occurrence → exactly 1 JobRun."""
    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "battle-sched-1@example.com")
    definition_id = await _make_due_job(client, headers, "test.battle_money")

    battle_counts.clear()
    scheduled_counts = await _concurrent_schedule_due(concurrency=50)

    assert sum(scheduled_counts) == 1, (
        f"expected 1 scheduled, got {scheduled_counts} sum={sum(scheduled_counts)}"
    )
    assert await _count_runs(definition_id) == 1

    # The run must be pending (not yet executed — scheduler only enqueues)
    async with SessionFactory() as session:
        run = (
            (await session.execute(select(JobRun).where(JobRun.definition_id == definition_id)))
            .scalars()
            .first()
        )
        assert run is not None
        assert run.status == JobRunStatus.PENDING.value

    # And next_run_at must have advanced exactly once — second tick must
    # not reschedule same occurrence
    async with SessionFactory() as session:
        scheduled_again = await JobService(session).schedule_due()
    assert scheduled_again == 0
    assert await _count_runs(definition_id) == 1


async def test_battle_concurrent_schedulers_ten_due_jobs_with_fifty_workers(app_client):
    """10 due jobs, 50 workers → exactly 10 runs, one per job."""
    client = app_client
    # Need multiple workspaces to get multiple definitions of same key?
    # Instead create 10 distinct due jobs
    # by using the same workspace but we only have test.battle_money/fast per workspace.
    # So create 5 workspaces × 2 battle keys = 10 definitions.
    from src.db.session import SessionFactory

    workspaces = []
    for i in range(5):
        _, ws, headers, _ = await setup_workspace(client, f"battle-multi-{i}@example.com")
        workspaces.append((ws, headers))

    # Make all 10 definitions due
    for _ws, headers in workspaces:
        for key in ("test.battle_money", "test.battle_fast"):
            jobs = (await client.get("/api/v1/jobs", headers=headers)).json()
            job = _by_key(jobs, key)
            async with SessionFactory() as session:
                d = await session.get(JobDefinition, job["id"])
                d.enabled = True
                d.next_run_at = now_utc() - timedelta(seconds=5)
                await session.commit()

    scheduled_counts = await _concurrent_schedule_due(concurrency=50)
    assert sum(scheduled_counts) == 10, f"expected 10, got sum={sum(scheduled_counts)}"

    # Verify each definition has exactly 1 run
    for _ws, headers in workspaces:
        for key in ("test.battle_money", "test.battle_fast"):
            jobs = (await client.get("/api/v1/jobs", headers=headers)).json()
            job = _by_key(jobs, key)
            assert await _count_runs(job["id"]) == 1


async def test_battle_scheduler_under_high_contention_100_workers(app_client):
    """Stress: 100 concurrent schedulers, single due job."""
    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "battle-100@example.com")
    definition_id = await _make_due_job(client, headers, "test.battle_fast")
    scheduled_counts = await _concurrent_schedule_due(concurrency=100)
    assert sum(scheduled_counts) == 1
    assert await _count_runs(definition_id) == 1


# ---------------------------------------------------------------------------
# 2. Executor atomicity — the second barrier (NATS redelivery, worker crash)
# ---------------------------------------------------------------------------


async def test_battle_concurrent_executors_single_pending_run_executes_once(app_client):
    """50 executors race to claim the same PENDING run → handler runs exactly once."""
    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "battle-exec-1@example.com")
    definition_id = await _make_due_job(client, headers, "test.battle_money")

    # Schedule exactly one pending run via a single scheduler tick
    async with SessionFactory() as session:
        assert await JobService(session).schedule_due() == 1

    async with SessionFactory() as session:
        run = (
            (await session.execute(select(JobRun).where(JobRun.definition_id == definition_id)))
            .scalars()
            .first()
        )
        assert run is not None
        run_id = run.id

    battle_counts.clear()
    # Give NATS/inprocess bus time to deliver the scheduled run, then cancel its auto-execution
    # by waiting a bit and then racing our own executors. The pending run
    # is still pending at this point
    # if we are fast enough; but to be deterministic, we ensure status is still pending
    # (the background executor hasn't claimed it yet — scheduler loop is disabled in tests).
    # In test env, the scheduler loop is disabled, but the jobs.execute consumer still runs.
    # The run we just scheduled was published via bus — the consumer will claim it within ~100ms.
    # To avoid that race, create a run directly without publishing, then race executors.
    # So recreate: make a pending run manually without bus publish.
    async with SessionFactory() as session:
        # Reset to pending if background consumer already claimed it
        run = await session.get(JobRun, run_id)
        if run.status != JobRunStatus.PENDING.value:
            # Create a fresh pending run for the battle
            from src.models.jobs import JobDefinition, JobTrigger

            definition = await session.get(JobDefinition, definition_id)
            run2 = JobRun(
                definition_id=definition.id,
                workspace_id=definition.workspace_id,
                status=JobRunStatus.PENDING.value,
                trigger=JobTrigger.MANUAL.value,
                params={},
                scheduled_at=now_utc(),
            )
            session.add(run2)
            await session.commit()
            run_id = run2.id
            battle_counts.clear()
        else:
            battle_counts.clear()

    await _concurrent_execute(run_id, concurrency=50)

    # Handler must have run exactly once despite 50 concurrent claim attempts
    assert battle_counts.get(run_id, 0) == 1, (
        f"handler executed {battle_counts.get(run_id, 0)} times, expected 1"
    )

    async with SessionFactory() as session:
        run = await session.get(JobRun, run_id)
        assert run.status == JobRunStatus.SUCCESS.value
        # Exactly one set of logs for this run_id
        logs = (
            (await session.execute(select(JobLogEntry).where(JobLogEntry.run_id == run_id)))
            .scalars()
            .all()
        )
        # At least the print line, not duplicated 50x
        money_logs = [log for log in logs if "BATTLE" in log.message]
        assert len(money_logs) == 1, f"expected 1 money log, got {len(money_logs)}: {money_logs}"


async def test_battle_concurrent_executors_redelivery_via_bus(app_client):
    """Simulate NATS redelivery / at-least-once publish: publish same run_id 20x."""
    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "battle-redeliver@example.com")
    definition_id = await _make_due_job(client, headers, "test.battle_money")

    # Create a pending run without bus publish, then publish same message many times
    from src.db.session import SessionFactory
    from src.models.jobs import JobTrigger

    async with SessionFactory() as session:
        definition = await session.get(JobDefinition, definition_id)
        run = JobRun(
            definition_id=definition.id,
            workspace_id=definition.workspace_id,
            status=JobRunStatus.PENDING.value,
            trigger=JobTrigger.MANUAL.value,
            params={},
            scheduled_at=now_utc(),
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    battle_counts.clear()

    # Simulate 20 NATS redeliveries (or 20 workers receiving same
    # workqueue message due to ack_wait timeout)
    await _concurrent_execute(run_id, concurrency=20)

    assert battle_counts.get(run_id, 0) == 1

    async with SessionFactory() as session:
        run = await session.get(JobRun, run_id)
        assert run.status == JobRunStatus.SUCCESS.value


async def test_battle_executor_idempotent_after_terminal(app_client):
    """A run already SUCCESS must never be re-executed, even with 30 concurrent redeliveries."""
    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "battle-idem@example.com")
    definition_id = await _make_due_job(client, headers, "test.battle_money")

    # Create and execute once to reach SUCCESS
    from src.jobs.executor import execute_run
    from src.models.jobs import JobTrigger

    async with SessionFactory() as session:
        definition = await session.get(JobDefinition, definition_id)
        run = JobRun(
            definition_id=definition.id,
            workspace_id=definition.workspace_id,
            status=JobRunStatus.PENDING.value,
            trigger=JobTrigger.MANUAL.value,
            params={},
            scheduled_at=now_utc(),
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    battle_counts.clear()
    await execute_run(run_id)
    assert battle_counts.get(run_id, 0) == 1

    # Now 30 concurrent redeliveries after terminal — must not re-execute
    battle_counts.clear()
    await asyncio.gather(*[execute_run(run_id) for _ in range(30)])
    assert battle_counts.get(run_id, 0) == 0, "terminal run was re-executed!"

    async with SessionFactory() as session:
        run = await session.get(JobRun, run_id)
        assert run.status == JobRunStatus.SUCCESS.value
        assert run.duration_ms is not None


async def test_battle_money_job_not_double_charged_concurrent_execute(app_client):
    """Money scenario: concurrent executors must not double-charge."""
    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "battle-money-2@example.com")
    definition_id = await _make_due_job(client, headers, "test.battle_money")

    from src.models.jobs import JobTrigger

    async with SessionFactory() as session:
        definition = await session.get(JobDefinition, definition_id)
        run = JobRun(
            definition_id=definition.id,
            workspace_id=definition.workspace_id,
            status=JobRunStatus.PENDING.value,
            trigger=JobTrigger.MANUAL.value,
            params={},
            scheduled_at=now_utc(),
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    battle_counts.clear()
    # 30 workers race — only one should charge
    await _concurrent_execute(run_id, concurrency=30)
    total_charges = sum(1 for rid, cnt in battle_counts.items() if cnt > 0)
    assert total_charges == 1
    assert battle_counts[run_id] == 1


# ---------------------------------------------------------------------------
# 3. End-to-end via HTTP (simulates multiple uvicorn workers handling /execute)
# ---------------------------------------------------------------------------


async def test_battle_concurrent_http_execute_now_does_not_duplicate_scheduled_occurrence(
    app_client,
):
    """Concurrent POST /execute (manual) each creates its own run —
    but concurrent schedule_due must not."""
    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "battle-http@example.com")
    definition_id = await _make_due_job(client, headers, "test.battle_fast")

    # Concurrent schedulers must still produce exactly 1 scheduled run
    scheduled = await _concurrent_schedule_due(concurrency=20)
    assert sum(scheduled) == 1
    assert await _count_runs(definition_id) == 1

    # Concurrent manual triggers are intentional duplicates — each should create a run
    # (manual runs are not deduplicated, they are user-intentional)
    manual_results = await asyncio.gather(
        *[
            client.post(f"/api/v1/jobs/{definition_id}/execute", json={}, headers=headers)
            for _ in range(5)
        ]
    )
    assert all(r.status_code == 201 for r in manual_results)
    assert await _count_runs(definition_id) == 6  # 1 scheduled + 5 manual


# ---------------------------------------------------------------------------
# 4. In-process bus single-delivery in dev, workqueue in prod
# ---------------------------------------------------------------------------


async def test_battle_inprocess_bus_delivers_jobs_execute_to_single_consumer(app_client):
    """In dev, jobs.execute published once must be consumed once (no fanout)."""
    from src.db.session import SessionFactory
    from src.events.subjects import Subjects

    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "battle-bus@example.com")
    definition_id = await _make_due_job(client, headers, "test.battle_money")

    # Create pending run and publish via the app's bus (the same bus the worker consumes)
    from src.main import app
    from src.models.jobs import JobTrigger

    async with SessionFactory() as session:
        definition = await session.get(JobDefinition, definition_id)
        run = JobRun(
            definition_id=definition.id,
            workspace_id=definition.workspace_id,
            status=JobRunStatus.PENDING.value,
            trigger=JobTrigger.MANUAL.value,
            params={},
            scheduled_at=now_utc(),
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    battle_counts.clear()
    bus = app.state.container.bus
    # Publish same run_id 10 times rapidly (simulates NATS redelivery / duplicate publish)
    await asyncio.gather(
        *[bus.publish(Subjects.JOBS_EXECUTE, {"run_id": run_id}) for _ in range(10)]
    )

    # Wait for consumer to process (inprocess bus is async queue)
    for _ in range(30):
        if battle_counts.get(run_id, 0) >= 1:
            break
        await asyncio.sleep(0.1)

    assert battle_counts.get(run_id, 0) == 1, f"bus delivered {battle_counts.get(run_id, 0)} times"

    # Even after waiting, no second execution
    await asyncio.sleep(0.3)
    assert battle_counts.get(run_id, 0) == 1


# ---------------------------------------------------------------------------
# 5. Scheduler + executor interaction under load
# ---------------------------------------------------------------------------


async def test_battle_scheduler_and_executor_no_lost_runs_under_load(app_client):
    """20 schedulers + 20 executors racing on same due job → no lost runs, no duplicates."""
    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "battle-mixed@example.com")
    definition_id = await _make_due_job(client, headers, "test.battle_fast")

    # Launch schedulers and also try to execute any runs that appear
    async def sched_worker():
        async with SessionFactory() as session:
            return await JobService(session).schedule_due()

    sched_results = await asyncio.gather(*[sched_worker() for _ in range(20)])
    assert sum(sched_results) == 1
    assert await _count_runs(definition_id) == 1

    # Now race executors on that one pending run
    async with SessionFactory() as session:
        run = (
            (await session.execute(select(JobRun).where(JobRun.definition_id == definition_id)))
            .scalars()
            .first()
        )
        run_id = run.id

    battle_counts.clear()
    await _concurrent_execute(run_id, concurrency=20)
    assert battle_counts.get(run_id, 0) == 1
