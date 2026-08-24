"""Developer-facing contract for scheduled jobs.

Services register job specs (metadata + handler) with `job_registry`; the
framework provisions a `JobDefinition` row per scope (one per workspace for
workspace-scoped jobs, one shared row for global jobs) and takes care of
scheduling, execution, logging and history.
"""

from src.jobs.capture import (
    RunLogCollector,
    install_run_capture,
    reset_run_log_collector,
    run_log_collector,
    set_run_log_collector,
    uninstall_run_capture,
)
from src.jobs.registry import (
    JobContext,
    JobHandler,
    JobParamType,
    JobSpec,
    ValidationError,
    job_registry,
    next_cron_occurrence,
    validate_cron_schedule,
    validate_params,
)

__all__ = [
    "JobContext",
    "JobHandler",
    "JobParamType",
    "JobSpec",
    "RunLogCollector",
    "ValidationError",
    "install_run_capture",
    "job_registry",
    "next_cron_occurrence",
    "reset_run_log_collector",
    "run_log_collector",
    "set_run_log_collector",
    "uninstall_run_capture",
    "validate_cron_schedule",
    "validate_params",
]
