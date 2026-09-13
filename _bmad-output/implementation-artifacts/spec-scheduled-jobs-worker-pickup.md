---
title: 'Fix scheduled jobs abandoned — scheduler never publishes to worker'
type: 'bugfix'
created: '2026-08-30'
status: 'done'
review_loop_iteration: 0
context: []
baseline_commit: '85012d62c2c288f3784b165f1ad92973cdf0eb5e'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every enabled scheduled job (workspace `invitations.expire_stale` and global `demo.global_daily_report`) creates a `job_runs` row on schedule but fails with `abandoned: no worker completed this run` — never picked up by a worker. Previous scheduled/automatic runs show only `failed` with that error, while manual `POST /execute` succeeds. Root cause is the scheduler enqueues without publishing `jobs.execute`.

**Approach:** Wire the deployment `EventBus` into `JobScheduler` so `schedule_due` can publish `jobs.execute` via `JobService.create_run`; update `main.py` lifespan to inject `container.bus`. Keep the bus optional for unit-test scheduling assertions.

## Boundaries & Constraints

**Always:** Scheduler `tick()` must publish via bus when present; manual `POST /execute` path unchanged (already passes bus); `register_builtin_jobs()` remains idempotent; `fail_stale_runs` / `prune_history` housekeeping stays hourly; InProcess and NATS buses both receive the publish (durable `jobs.execute`).

**Ask First:** Changing `JobService.schedule_due` to require a bus (breaking existing test callers that assert pending state without publish); adding new job specs or changing `default_enabled`.

**Never:** Switch scheduler to synchronous direct `execute_run` (bypasses bus durability and load-balancing); add new env var; modify `job_registry` registration semantics; commit DB files (`*.db`).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Scheduled tick with bus | enabled `invitations.expire_stale` due 5s ago, scheduler has bus | `schedule_due` publishes `jobs.execute {run_id}`; consumer claims `pending→running` and finishes `success`; logs contain `[Demo]` lines | publish failure bubbles as exception logged by scheduler loop |
| Scheduled tick without bus (test) | `JobService(session).schedule_due()` with no bus (legacy test) | still creates `pending` `JobRun` and advances `next_run_at`; no publish attempted | N/A |
| Manual execute | `POST /jobs/{id}/execute` with `jobs:edit` | creates `pending` + publishes `jobs.execute`; run reaches `success` within 10s | `403` if missing permission |
| Missed ignored policy | global `test.boom` with `missed_policy=ignore` due 3h ago, bus present | scheduler skips creation, only advances `next_run_at`; no run, no publish | N/A |
| Worker crash | pending run not acked before `fail_stale_runs` cutoff | marked `failed abandoned: no worker completed this run` with `finished_at` set | housekeeping runs next tick |
| Bus not started edge | scheduler publishes before `registry.start()` (should not happen) | publish buffered via `NatsEventBus._pending_publishes` / `InProcess` queue, delivered after start | warn/log if bus stopped |

</frozen-after-approval>

## Code Map

- `apps/api/src/jobs/scheduler.py:1` — `class JobScheduler` with `tick()` currently doing `JobService(session).schedule_due()` without bus → add `bus: EventBus | None` param, store `self._bus`, pass `JobService(session, self._bus)` in `tick()` and housekeeping if needed
- `apps/api/src/main.py:39` — `lifespan()` builds `JobScheduler()` with no args and starts after `registry.wire/start` → change to `JobScheduler(bus=container.bus)` so scheduled runs publish
- `apps/api/src/services/jobs.py:339` — `schedule_due()` creates runs via `create_run()` which does `if self._bus is not None: publish Subjects.JOBS_EXECUTE` → already correct, just needs scheduler to supply bus
- `apps/api/src/workflows/__init__.py:366` — `on_job_execute` durable consumer calling `execute_run(run_id)` → verifies worker path exists (load-balanced, ack after success)
- `apps/api/src/jobs/executor.py:131` — `execute_run()` with atomic `pending→running` CAS and `register_builtin_jobs()` → confirms handler lookup `job_registry.get(key)` will succeed after fix (currently never reached for scheduled runs)
- `apps/api/src/events/bus.py:39` — `EventBus` ABC with `publish/subscribe/start/stop` → scheduler dependency type
- `apps/api/src/events/subjects.py:48` — `Subjects.JOBS_EXECUTE = "jobs.execute"` durable subject, must not be transient
- `apps/api/tests/test_jobs.py:439` — existing scheduler atomicity test using `JobService(session).schedule_due()` without bus asserts pending → keep passing
- `apps/api/tests/test_jobs_atomicity_battle.py:144` — battle tests with `_concurrent_schedule_due` without bus → should remain green

## Tasks & Acceptance

**Execution:**
- [x] `apps/api/src/jobs/scheduler.py` — add `bus: EventBus | None` to `JobScheduler.__init__`, store it, change `tick()` to `JobService(session, self._bus).schedule_due()`; keep `__init__(tick_seconds=...)` backward-compatible; add optional `bus` setter if needed for tests; keep `HOUSEKEEPING_INTERVAL_SECONDS` behavior
- [x] `apps/api/src/main.py` — in `lifespan`, instantiate `JobScheduler(bus=container.bus)` after `registry` wired/started; keep `install_run_capture()` ordering; ensure `app.state.job_scheduler` still set
- [x] `apps/api/tests/test_jobs.py` — add regression test `test_scheduled_run_is_executed_via_bus` (or extend existing) that enables a workspace job due 5s ago, runs `JobService(session, app.state.container.bus).schedule_due()`, then waits for `jobs.execute` consumer to finish and asserts `success` and log lines (alternatively concurrent manual verification)
- [x] Verify embedded PG `job_runs` `scheduled` previous failures are now succeeded on fresh schedule (manual adhoc script or doc)

**Acceptance Criteria:**
- Given an enabled workspace job `invitations.expire_stale` with `next_run_at` 5s ago, when `JobScheduler(bus=container.bus).tick()` runs, then a `JobRun` is created with `trigger=scheduled`, `status` transitions `pending→success` within 10s via the `jobs.execute` worker, and `JobLogEntry` rows contain `[Demo]` messages
- Given an enabled global job `demo.global_daily_report` due, when scheduler ticks, then exactly one scheduled run is created and executed (no duplicate) and `next_run_at` advances
- Given `JobService(session)` invoked without bus (existing tests), when `schedule_due()` is called, then it still creates a `pending` run but does not crash (publish skipped) — backward compat
- Given a missed occurrence with `missed_policy=ignore` due 3h ago, when scheduler ticks, then no run is created and `next_run_at` advances (existing test still passes)
- Given manual `POST /jobs/{id}/execute` with valid `jobs:edit`, when called, then run still succeeds as before (no regression)

## Spec Change Log

## Design Notes

Scheduler currently does:

```python
async def tick(self):
    async with SessionFactory() as session:
        scheduled = await JobService(session).schedule_due()
```

`JobService.create_run` only publishes when `self._bus is not None`:

```python
if self._bus is not None:
    await self._bus.publish(Subjects.JOBS_EXECUTE, {"run_id": run.id})
```

Thus every scheduled run is created `pending` but never enqueued → `fail_stale_runs` later marks it `abandoned: no worker completed this run` (observed: 20 failed `invitations.expire_stale` + 2 `demo.global_daily_report` in embedded PG).

Fix is one-line wiring: `JobService(session, self._bus)`.

## Verification

**Commands:**
- `uv run --no-cache pytest tests/test_jobs.py tests/test_jobs_atomicity_battle.py -v` -- expected: 26 passed
- `uv run --no-cache python -c "import asyncio; ... schedule due via bus and wait for success"` -- expected: scheduled==1 and run status success (ad-hoc verification script)

**Manual checks (if no CLI):**
- Inspect `job_runs` after a scheduler tick: `select status, trigger, error from job_runs order by created_at desc limit 5` should show latest scheduled run `success` not `failed abandoned`

