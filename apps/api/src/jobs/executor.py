"""Job execution engine.

Runs on the consumer side of the `jobs.execute` subject: claims a pending run
atomically, executes the handler under log capture, and persists status,
duration and captured logs. Manages its own short-lived DB sessions so a
long-running job never pins a pooled connection (same discipline as the
workflow subscribers).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import traceback

from sqlalchemy import update

from src.core.dates import now_utc
from src.core.security.crypto import SecretCipher
from src.db.session import SessionFactory
from src.jobs.capture import (
    CapturedEntry,
    RunLogCollector,
    install_run_capture,
    reset_run_log_collector,
    set_run_log_collector,
)
from src.jobs.registry import JobContext, job_registry, register_builtin_jobs
from src.models.jobs import JobDefinition, JobLogEntry, JobRun, JobRunStatus
from src.models.workspace import Workspace
from src.settings import settings

logger = logging.getLogger(__name__)

FLUSH_INTERVAL_SECONDS = 2.0

_cipher: SecretCipher | None = None


def _get_cipher() -> SecretCipher:
    global _cipher
    if _cipher is None:
        _cipher = SecretCipher(
            settings.fernet_key_list, encrypt_version=settings.secret_encrypt_version
        )
    return _cipher


async def _invoke_handler(handler, ctx: JobContext) -> None:
    """Support async handlers and sync ones (offloaded to a worker thread).

    `asyncio.to_thread` copies the current contextvars, so log capture keeps
    working inside sync handlers.
    """
    if inspect.iscoroutinefunction(handler):
        await handler(ctx)
    else:
        await asyncio.to_thread(handler, ctx)


class _LogPersister:
    """Drains the run's collector into job_logs rows every few seconds."""

    def __init__(self, run_id: str, collector: RunLogCollector) -> None:
        self._run_id = run_id
        self._collector = collector
        self._seq = 0
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.flush()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            await self.flush()

    async def cancel(self) -> None:
        """Stop the loop WITHOUT flushing (shutdown path — exit fast)."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def flush(self) -> None:
        entries, dropped = self._collector.drain()
        if dropped:
            entries.append(
                CapturedEntry(
                    ts=now_utc(), level="WARNING", message=f"… {dropped} log lines dropped (cap)"
                )
            )
        if not entries:
            return
        rows = [
            dict(seq=self._seq + i, ts=e.ts, level=e.level[:10], message=e.message)
            for i, e in enumerate(entries)
        ]
        # Retry transient write failures (e.g. sqlite lock contention); the
        # buffer is only advanced once the rows are durably committed.
        for attempt in range(3):
            try:
                async with SessionFactory() as session:
                    session.add_all(JobLogEntry(run_id=self._run_id, **row) for row in rows)
                    await session.commit()
                self._seq += len(rows)
                return
            except Exception:
                if attempt == 2:
                    logger.exception(
                        "failed to persist %d log lines for run %s", len(rows), self._run_id
                    )
                else:
                    await asyncio.sleep(0.2 * (attempt + 1))
        self._collector.requeue(entries)


async def execute_run(run_id: str) -> None:
    """Claim and execute one job run. Safe to call for an unknown/claimed run.

    Workspace runs whose workspace (or definition) no longer exists fail fast
    instead of executing — a run queued just before a workspace delete must
    not produce new rows for the deleted workspace.
    """
    register_builtin_jobs()

    # Atomic claim: exactly one worker transitions pending → running, even
    # when the bus redelivers the message or several replicas receive it.
    started_at = now_utc()
    async with SessionFactory() as session:
        result = await session.execute(
            update(JobRun)
            .where(JobRun.id == run_id, JobRun.status == JobRunStatus.PENDING.value)
            .values(status=JobRunStatus.RUNNING.value, started_at=started_at)
        )
        if result.rowcount != 1:
            await session.commit()
            return
        run = await session.get(JobRun, run_id)
        # Only stamp last_run_at when the workspace (if any) still exists —
        # the claim above already flipped the run to running, and the
        # workspace-gone check below fails it right away.
        definition = (
            await session.get(JobDefinition, run.definition_id) if run is not None else None
        )
        workspace_gone = (
            definition is not None
            and definition.workspace_id is not None
            and await session.get(Workspace, definition.workspace_id) is None
        )
        if run is not None and not workspace_gone:
            # "Last run" reflects the most recent actual execution start —
            # manual and scheduled runs alike.
            await session.execute(
                update(JobDefinition)
                .where(JobDefinition.id == run.definition_id)
                .values(last_run_at=started_at)
            )
        await session.commit()

    assert run is not None
    async with SessionFactory() as session:
        # Re-read: the first session already committed the claim above and
        # may be holding stale state.
        definition = await session.get(JobDefinition, run.definition_id)
        workspace_gone = (
            definition is not None
            and definition.workspace_id is not None
            and await session.get(Workspace, definition.workspace_id) is None
        )

    if workspace_gone:
        await _finish(run_id, JobRunStatus.FAILED, "workspace no longer exists")
        return

    if definition is None:
        await _finish(run_id, JobRunStatus.FAILED, "job definition no longer exists")
        return

    spec = job_registry.get(definition.key)
    if spec is None or spec.handler is None:
        await _finish(run_id, JobRunStatus.FAILED, f"handler {definition.key!r} is not registered")
        return

    cipher = _get_cipher()
    params = dict(run.params or {})
    for name, rules in (definition.params_schema or {}).items():
        value = params.get(name)
        if rules.get("type") == "password" and isinstance(value, str) and value.startswith("v"):
            try:
                params[name] = cipher.decrypt(value)
            except Exception:
                logger.exception("cannot decrypt param %s; passing stored value", name)

    ctx = JobContext(
        run_id=run.id,
        job_key=definition.key,
        workspace_id=definition.workspace_id,
        params=params,
    )

    install_run_capture()
    collector = RunLogCollector()
    token = set_run_log_collector(collector)
    persister = _LogPersister(run.id, collector)
    started_at = now_utc()
    timeout = definition.timeout_seconds or settings.jobs_default_timeout_seconds
    status: JobRunStatus
    error: str | None = None
    cancelled = False
    persister.start()
    try:
        await asyncio.wait_for(_invoke_handler(spec.handler, ctx), timeout=timeout)
        status = JobRunStatus.SUCCESS
    except TimeoutError:
        status = JobRunStatus.TIMED_OUT
        error = f"execution exceeded the {timeout}s timeout"
        logger.warning("job %s run %s timed out after %ss", definition.key, run.id, timeout)
    except asyncio.CancelledError:
        # Shutdown mid-run: exit FAST (no DB work while the loop is tearing
        # down). The run stays running; `fail_stale_runs` housekeeping marks
        # it abandoned, and JetStream redelivers unacknowledged messages.
        cancelled = True
        raise
    except Exception as exc:
        status = JobRunStatus.FAILED
        error = "".join(traceback.format_exception(exc))
        logger.exception("job %s run %s failed", definition.key, run.id)
    finally:
        reset_run_log_collector(token)
        if cancelled:
            await persister.cancel()
        else:
            await persister.stop()

    if not cancelled:
        await _finish(run.id, status, error, started_at)


async def _finish(
    run_id: str,
    status: JobRunStatus,
    error: str | None,
    started_at=None,
) -> None:
    finished_at = now_utc()
    duration_ms = None
    if started_at is not None:
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    job_key: str | None = None
    async with SessionFactory() as session:
        run = await session.get(JobRun, run_id)
        if run is None:
            return
        definition = await session.get(JobDefinition, run.definition_id)
        job_key = definition.key if definition is not None else None
        run.status = status.value
        run.finished_at = finished_at
        run.duration_ms = duration_ms
        run.error = error[:8000] if error else None
        await session.commit()
    if job_key is not None:
        from src.core.metrics import observe_job_run

        observe_job_run(key=job_key, status=status.value)
