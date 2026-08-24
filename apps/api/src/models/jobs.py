from __future__ import annotations

import uuid

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StrEnum, StringUUID, TimestampMixin


class JobScope(StrEnum):
    WORKSPACE = "workspace"
    GLOBAL = "global"


class JobRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class JobTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class MissedJobPolicy(StrEnum):
    """What happens to occurrences that came due while the scheduler was down.

    SINGLE fires one catch-up execution immediately, then advances to the next
    future occurrence. IGNORE skips missed occurrences entirely.
    """

    SINGLE = "single"
    IGNORE = "ignore"


class JobDefinition(Base, TimestampMixin):
    """A registered scheduled job instance.

    Rows are provisioned from the in-code registry (src/jobs): global specs get
    exactly one row (workspace_id NULL); workspace specs get one row per
    workspace so each workspace configures its own schedule/params/enabled.
    The DB row — not the code spec — is the source of truth for scheduling.
    """

    __tablename__ = "job_definitions"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Registry key of the handler function (unique per scope+workspace).
    key: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(StringUUID(), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cron_schedule: Mapped[str] = mapped_column(String(100), nullable=False)
    params_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    missed_policy: Mapped[str] = mapped_column(
        String(10), default=MissedJobPolicy.SINGLE.value, nullable=False
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=600)
    # Next due occurrence (UTC). NULL while disabled; recomputed on enable/edit.
    next_run_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def scope(self) -> JobScope:
        return JobScope.GLOBAL if self.workspace_id is None else JobScope.WORKSPACE


class JobRun(Base, TimestampMixin):
    """One execution of a job definition.

    `params` snapshots the configuration used for THIS run (encrypted for
    password-type values) so history stays truthful even if the definition is
    edited later.
    """

    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    definition_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(StringUUID(), index=True, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=JobRunStatus.PENDING.value, index=True, nullable=False
    )
    trigger: Mapped[str] = mapped_column(String(10), default=JobTrigger.SCHEDULED.value)
    actor_user_id: Mapped[str | None] = mapped_column(StringUUID(), index=True, nullable=True)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scheduled_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class JobLogEntry(Base):
    """One captured log line (logging records + stdout/stderr writes)."""

    __tablename__ = "job_logs"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ts: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False, default="INFO")
    message: Mapped[str] = mapped_column(Text, nullable=False)


__all__ = [
    "JobDefinition",
    "JobLogEntry",
    "JobRun",
    "JobRunStatus",
    "JobScope",
    "JobTrigger",
    "MissedJobPolicy",
]
