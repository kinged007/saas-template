"""Scheduled jobs service: provisioning, configuration, scheduling, history.

Layering:
- Route-facing operations use the request-scoped session passed to the
  constructor (same pattern as the other services).
- The scheduler tick (`schedule_due`) runs on a short-lived background
  session owned by `src.jobs.scheduler`.
- Execution itself lives in `src.jobs.executor` (it manages its own sessions
  so a long-running job never pins a pooled connection).

Atomicity contract: `next_run_at` is ONLY ever written through this service,
always as aware UTC datetimes produced by `now_utc`/croniter. That makes the
compare-and-swap below exact on both Postgres and SQLite and guarantees a due
occurrence is claimed by exactly one replica.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dates import ensure_utc, iso_or_none, now_utc
from src.core.security.crypto import SecretCipher
from src.events.bus import EventBus
from src.jobs.registry import (
    PASSWORD_MASK,
    JobSpec,
    ValidationError,
    _coerce,
    default_params,
    job_registry,
    next_cron_occurrence,
    register_builtin_jobs,
    validate_cron_schedule,
)
from src.models.jobs import (
    JobDefinition,
    JobLogEntry,
    JobRun,
    JobRunStatus,
    JobTrigger,
    MissedJobPolicy,
)
from src.models.workspace import Workspace

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 8000


class JobError(Exception):
    pass


# ------------------------------------------------------------------ serializers


def _mask_params(schema: dict, params: dict) -> dict:
    """Mask password-type values for API responses (never leak ciphertext)."""
    masked = dict(params or {})
    for name, rules in (schema or {}).items():
        if rules.get("type") == "password" and masked.get(name) is not None:
            masked[name] = PASSWORD_MASK
    return masked


def job_to_dict(d: JobDefinition) -> dict:
    return {
        "id": d.id,
        "key": d.key,
        "workspace_id": d.workspace_id,
        "scope": d.scope.value,
        "name": d.name,
        "description": d.description,
        "cron_schedule": d.cron_schedule,
        "params_schema": d.params_schema or {},
        "params": _mask_params(d.params_schema, d.params),
        "enabled": d.enabled,
        "missed_policy": d.missed_policy,
        "timeout_seconds": d.timeout_seconds,
        "next_run_at": iso_or_none(d.next_run_at),
        "last_run_at": iso_or_none(d.last_run_at),
        "created_at": iso_or_none(d.created_at),
        "updated_at": iso_or_none(d.updated_at),
    }


def job_run_to_dict(r: JobRun, *, schema: dict | None = None) -> dict:
    data = {
        "id": r.id,
        "definition_id": r.definition_id,
        "workspace_id": r.workspace_id,
        "status": r.status,
        "trigger": r.trigger,
        "actor_user_id": r.actor_user_id,
        "scheduled_at": iso_or_none(r.scheduled_at),
        "started_at": iso_or_none(r.started_at),
        "finished_at": iso_or_none(r.finished_at),
        "duration_ms": r.duration_ms,
        "error": r.error,
        "created_at": iso_or_none(r.created_at),
    }
    if schema is not None:
        data["params"] = _mask_params(schema, r.params)
    return data


def job_log_to_dict(e: JobLogEntry) -> dict:
    return {
        "seq": e.seq,
        "ts": iso_or_none(e.ts),
        "level": e.level,
        "message": e.message,
    }


# --------------------------------------------------------------------- service


class JobService:
    def __init__(
        self,
        session: AsyncSession,
        bus: EventBus | None = None,
        cipher: SecretCipher | None = None,
    ) -> None:
        self._session = session
        self._bus = bus
        self._cipher = cipher

    # ------------------------------------------------------------ provisioning

    async def sync_definitions(self, *, workspace_ids: list[str] | None = None) -> None:
        """Reconcile job definition rows with registered specs. Idempotent.

        Code-owned fields (name, description, schema, timeout, defaults for
        NEW params) are refreshed on existing rows; user-owned fields
        (schedule, params, enabled, missed policy) are never overwritten.
        Definitions whose spec disappeared are disabled so they stop firing.
        """
        register_builtin_jobs()

        if workspace_ids is None:
            result = await self._session.execute(select(Workspace.id))
            workspace_ids = [row[0] for row in result.all()]

        for spec in job_registry.all():
            if spec.scope == "global":
                await self._upsert_definition(spec, workspace_id=None)
            else:
                for workspace_id in workspace_ids:
                    await self._upsert_definition(spec, workspace_id=workspace_id)

        await self._disable_orphaned_definitions({spec.key for spec in job_registry.all()})
        await self._session.commit()

    async def _upsert_definition(self, spec: JobSpec, workspace_id: str | None) -> None:
        stmt = select(JobDefinition).where(JobDefinition.key == spec.key)
        if workspace_id is None:
            stmt = stmt.where(JobDefinition.workspace_id.is_(None))
        else:
            stmt = stmt.where(JobDefinition.workspace_id == workspace_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = JobDefinition(
                key=spec.key,
                workspace_id=workspace_id,
                name=spec.name,
                description=spec.description,
                cron_schedule=spec.schedule,
                params_schema=spec.params_schema,
                params=self._provision_defaults(spec),
                enabled=spec.default_enabled,
                missed_policy=spec.missed_policy,
                timeout_seconds=spec.timeout_seconds,
                next_run_at=(
                    next_cron_occurrence(spec.schedule, now_utc()) if spec.default_enabled else None
                ),
            )
            self._session.add(row)
            scope = "global" if workspace_id is None else f"workspace {workspace_id}"
            logger.info("provisioned job %s (%s)", spec.key, scope)
            return
        # Existing row: refresh code-owned metadata and fill in defaults for
        # params introduced after the row was created.
        row.name = spec.name
        row.description = spec.description
        row.params_schema = spec.params_schema
        row.timeout_seconds = spec.timeout_seconds
        stored = dict(row.params or {})
        for name, value in self._provision_defaults(spec).items():
            stored.setdefault(name, value)
        row.params = stored

    def _provision_defaults(self, spec: JobSpec) -> dict[str, Any]:
        """Initial param values. Non-null password defaults are stored encrypted."""
        defaults = default_params(spec.params_schema)
        if self._cipher is not None:
            for name, rules in (spec.params_schema or {}).items():
                if rules.get("type") == "password" and defaults.get(name) is not None:
                    defaults[name] = self._cipher.encrypt(str(defaults[name]))
        return defaults

    async def _disable_orphaned_definitions(self, live_keys: set[str]) -> None:
        stmt = select(JobDefinition).where(
            JobDefinition.enabled.is_(True), JobDefinition.key.not_in(live_keys or {"__none__"})
        )
        for row in (await self._session.execute(stmt)).scalars().all():
            row.enabled = False
            row.next_run_at = None
            logger.warning("disabled orphaned job definition %s (spec removed)", row.key)

    # ------------------------------------------------------------------ queries

    async def list_definitions(self, workspace_id: str | None) -> list[JobDefinition]:
        stmt = select(JobDefinition).where(JobDefinition.workspace_id == workspace_id)
        stmt = stmt.order_by(JobDefinition.name.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_definition(self, definition_id: str) -> JobDefinition | None:
        return await self._session.get(JobDefinition, definition_id)

    # ------------------------------------------------------------------- update

    async def update_definition(
        self,
        definition: JobDefinition,
        *,
        cron_schedule: str | None = None,
        params: dict[str, Any] | None = None,
        enabled: bool | None = None,
        missed_policy: str | None = None,
    ) -> JobDefinition:
        changes: dict[str, Any] = {}
        if cron_schedule is not None and cron_schedule != definition.cron_schedule:
            validate_cron_schedule(cron_schedule)
            changes["cron_schedule"] = {"from": definition.cron_schedule, "to": cron_schedule}
            definition.cron_schedule = cron_schedule
        if params is not None:
            prepared = self._merge_params(definition, params)
            changed_keys = [
                name
                for name, value in prepared.items()
                if value != (definition.params or {}).get(name)
            ]
            if changed_keys:
                # Never log secret values — record which keys changed only.
                changes["params"] = {"changed": sorted(changed_keys)}
                definition.params = prepared
        if missed_policy is not None and missed_policy != definition.missed_policy:
            if missed_policy not in (MissedJobPolicy.SINGLE.value, MissedJobPolicy.IGNORE.value):
                raise ValidationError("missed_policy must be 'single' or 'ignore'")
            changes["missed_policy"] = {"from": definition.missed_policy, "to": missed_policy}
            definition.missed_policy = missed_policy
        if enabled is not None and enabled != definition.enabled:
            changes["enabled"] = {"from": definition.enabled, "to": enabled}
            definition.enabled = enabled

        # Recompute the next occurrence whenever enablement or schedule changed.
        if "enabled" in changes or "cron_schedule" in changes:
            definition.next_run_at = (
                next_cron_occurrence(definition.cron_schedule, now_utc())
                if definition.enabled
                else None
            )

        await self._session.commit()
        # Server-side onupdate columns expire attributes at commit; reload so
        # serialization never triggers implicit (greenlet-illegal) IO.
        await self._session.refresh(definition)
        if changes:
            logger.info("job %s updated: %s", definition.key, ", ".join(changes))
        return definition

    def _merge_params(self, definition: JobDefinition, incoming: dict[str, Any]) -> dict[str, Any]:
        """Validate an incoming param patch against the schema.

        Unspecified fields keep their stored values; password fields sent as
        the mask sentinel (or omitted) keep their stored ciphertext; new
        password values are encrypted at rest.
        """
        schema = definition.params_schema or {}
        stored = definition.params or {}
        prepared: dict[str, Any] = {}
        for name, rules in schema.items():
            ptype = rules.get("type", "string")
            if ptype == "password":
                raw = incoming.get(name)
                if raw is None or raw == PASSWORD_MASK:
                    prepared[name] = stored.get(name, rules.get("default"))
                elif not isinstance(raw, str):
                    raise ValidationError(f"param {name!r} must be a string")
                else:
                    if self._cipher is None:
                        raise JobError("no cipher configured; cannot store secret parameters")
                    prepared[name] = self._cipher.encrypt(raw)
                continue
            if name in incoming and incoming[name] is not None:
                prepared[name] = _coerce(name, ptype, incoming[name], rules)
            elif stored.get(name) is not None:
                prepared[name] = stored[name]
            else:
                prepared[name] = rules.get("default")
        unknown = set(incoming) - set(schema)
        if unknown:
            raise ValidationError(f"unknown parameters: {', '.join(sorted(unknown))}")
        return prepared

    def decrypt_params(self, definition: JobDefinition) -> dict[str, Any]:
        """Plaintext view of stored params (execution-time only)."""
        params = dict(definition.params or {})
        schema = definition.params_schema or {}
        if self._cipher is None:
            return params
        for name, rules in schema.items():
            if rules.get("type") != "password":
                continue
            value = params.get(name)
            if isinstance(value, str) and value.startswith("v"):
                try:
                    params[name] = self._cipher.decrypt(value)
                except Exception:
                    logger.exception("failed to decrypt param %s for job %s", name, definition.key)
        return params

    # -------------------------------------------------------------- scheduling

    # Occurrences due less than this far in the past are normal fires; older
    # ones count as MISSED for the purposes of missed_policy. Slightly above
    # one tick so jitter never misclassifies a regular fire.
    MISS_GRACE_SECONDS = 30.0

    async def schedule_due(self) -> int:
        """One scheduler tick: claim due definitions and enqueue executions.

        Returns the number of runs scheduled. Missed occurrences (nothing
        fired around the due time, e.g. the deployment was down) fire ONCE as
        catch-up under the `single` policy and are skipped entirely under
        `ignore`; both policies advance `next_run_at` atomically via CAS, so
        exactly one replica claims each occurrence either way. Definitions
        whose workspace was deleted are skipped instead of scheduled, so the
        tick never resurrects rows in a deleted workspace.
        """
        now = now_utc()
        stmt = (
            select(JobDefinition)
            .outerjoin(Workspace, Workspace.id == JobDefinition.workspace_id)
            .where(
                JobDefinition.enabled.is_(True),
                JobDefinition.next_run_at.is_not(None),
                # Global rows (workspace_id NULL) pass; workspace rows need a live parent.
                (JobDefinition.workspace_id.is_(None)) | (Workspace.id.is_not(None)),
            )
        )
        due = [
            d
            for d in (await self._session.execute(stmt)).scalars().all()
            if ensure_utc(d.next_run_at) <= now
        ]
        scheduled = 0
        for definition in due:
            due_at = ensure_utc(definition.next_run_at)
            new_next = next_cron_occurrence(definition.cron_schedule, now)
            # CAS advance: only the replica that wins this update schedules
            # the occurrence. `last_run_at` is set by the executor when the
            # run actually starts, not at scheduling time.
            result = await self._session.execute(
                update(JobDefinition)
                .where(JobDefinition.id == definition.id, JobDefinition.next_run_at == due_at)
                .values(next_run_at=new_next)
            )
            if result.rowcount != 1:
                continue  # another replica claimed this occurrence
            await self._session.commit()

            is_missed = (now - due_at).total_seconds() > self.MISS_GRACE_SECONDS
            if is_missed and definition.missed_policy == MissedJobPolicy.IGNORE.value:
                logger.info(
                    "job %s: skipped missed occurrence due %s (policy=ignore)",
                    definition.key,
                    due_at,
                )
                continue

            try:
                run = await self.create_run(
                    definition, trigger=JobTrigger.SCHEDULED, scheduled_at=due_at
                )
            except JobError:
                logger.info(
                    "job %s: workspace %s deleted mid-tick, skipping",
                    definition.key,
                    definition.workspace_id,
                )
                continue
            scheduled += 1
            logger.debug("scheduled job %s run %s (due %s)", definition.key, run.id, due_at)
        return scheduled

    async def create_run(
        self,
        definition: JobDefinition,
        *,
        trigger: JobTrigger,
        scheduled_at: Any = None,
        actor_user_id: str | None = None,
    ) -> JobRun:
        """Insert a pending run (snapshotting current params) and enqueue it.

        Refuses workspace definitions whose workspace no longer exists, so a
        held definition object (or a mid-delete request) cannot insert rows
        into a deleted workspace.
        """
        if definition.workspace_id is not None:
            workspace = await self._session.get(Workspace, definition.workspace_id)
            if workspace is None:
                raise JobError("workspace not found")
        correlation_id = str(uuid.uuid4())
        run = JobRun(
            definition_id=definition.id,
            workspace_id=definition.workspace_id,
            status=JobRunStatus.PENDING.value,
            trigger=trigger.value,
            actor_user_id=actor_user_id,
            params=dict(definition.params or {}),
            scheduled_at=scheduled_at or now_utc(),
            correlation_id=correlation_id,
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        if self._bus is not None:
            from src.events.subjects import Subjects

            await self._bus.publish(
                Subjects.JOBS_EXECUTE,
                {"run_id": run.id},
                correlation_id=correlation_id,
            )
        return run

    # ------------------------------------------------------------- run history

    async def list_runs(
        self,
        definition_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[JobRun], int]:
        base = select(JobRun).where(JobRun.definition_id == definition_id)
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.order_by(None).subquery())
            )
        ).scalar_one()
        stmt = base.order_by(JobRun.scheduled_at.desc()).offset(offset).limit(limit)
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_run(self, run_id: str) -> JobRun | None:
        return await self._session.get(JobRun, run_id)

    async def list_run_logs(self, run_id: str) -> list[JobLogEntry]:
        stmt = (
            select(JobLogEntry).where(JobLogEntry.run_id == run_id).order_by(JobLogEntry.seq.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------- housekeeping

    async def prune_history(self, retention: int) -> int:
        """Delete runs (and their logs) beyond the newest `retention` per job."""
        removed = 0
        definition_ids = (await self._session.execute(select(JobDefinition.id))).scalars().all()
        for definition_id in definition_ids:
            ids_stmt = (
                select(JobRun.id)
                .where(JobRun.definition_id == definition_id)
                .order_by(JobRun.scheduled_at.desc(), JobRun.created_at.desc())
                .offset(retention)
            )
            stale = (await self._session.execute(ids_stmt)).scalars().all()
            if not stale:
                continue
            await self._session.execute(delete(JobLogEntry).where(JobLogEntry.run_id.in_(stale)))
            await self._session.execute(delete(JobRun).where(JobRun.id.in_(stale)))
            removed += len(stale)
        if removed:
            await self._session.commit()
            logger.info("pruned %d old job runs", removed)
        return removed

    async def fail_stale_runs(self, older_than_seconds: float) -> int:
        """Mark runs abandoned mid-flight (crash / lost worker) as failed.

        Without this a replica dying between claim and completion would leave
        the run in pending/running forever.
        """
        cutoff = now_utc() - timedelta(seconds=older_than_seconds)
        result = await self._session.execute(
            update(JobRun)
            .where(
                JobRun.status.in_([JobRunStatus.PENDING.value, JobRunStatus.RUNNING.value]),
                JobRun.created_at < cutoff,
            )
            .values(
                status=JobRunStatus.FAILED.value,
                error="abandoned: no worker completed this run",
                finished_at=now_utc(),
            )
        )
        if result.rowcount:
            await self._session.commit()
            logger.warning("marked %d stale job runs as failed", result.rowcount)
        return result.rowcount
