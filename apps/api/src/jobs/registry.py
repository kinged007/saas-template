"""Job registry: in-code job specs and their validation helpers.

A `JobSpec` is everything the developer declares about a scheduled job —
identity, default schedule/params/enabled state, scope, timeout and the
handler callable. The DB rows provisioned from specs (see
`JobService.sync_definitions`) carry the user-editable state; specs are the
code-owned baseline reconciled on startup.

Param schemas are a pragmatic JSON-schema subset:

    {"batch_size": {"type": "int", "default": 500, "min": 1, "max": 10_000,
                    "label": "Batch size", "help": "..."}}

Supported types: int, float, string, password (encrypted at rest), date
(ISO `YYYY-MM-DD`).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from croniter import croniter

from src.models.jobs import MissedJobPolicy

logger = logging.getLogger(__name__)

PARAM_TYPES = ("int", "float", "string", "password", "date")
# Sentinel returned to clients for password params; sending it back on PATCH
# means "keep the stored value".
PASSWORD_MASK = "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"


class ValidationError(Exception):
    """Invalid cron expression or job parameters."""


class JobParamType(StrEnum):
    INT = "int"
    FLOAT = "float"
    STRING = "string"
    PASSWORD = "password"
    DATE = "date"


@dataclass
class JobContext:
    """Handed to every job handler invocation."""

    run_id: str
    job_key: str
    # None for global jobs.
    workspace_id: str | None
    # Decrypted parameter values for this run.
    params: dict[str, Any]

    def session(self):
        """Open a DB session scoped to this execution.

        Jobs own their transactions: `async with ctx.session() as db: ...`.
        """
        from src.db.session import SessionFactory

        return SessionFactory()


JobHandler = Callable[[JobContext], Awaitable[None] | None]


@dataclass
class JobSpec:
    key: str
    name: str
    description: str
    # Bound by the @job_registry.register decorator; never set inline.
    handler: JobHandler | None = None
    scope: str = "workspace"  # "workspace" | "global"
    schedule: str = "0 * * * *"
    params_schema: dict[str, dict[str, Any]] = field(default_factory=dict)
    default_enabled: bool = False
    missed_policy: str = MissedJobPolicy.SINGLE.value
    timeout_seconds: int = 600


def validate_cron_schedule(expr: str) -> None:
    if not isinstance(expr, str) or not expr.strip():
        raise ValidationError("cron schedule must be a non-empty string")
    if len(expr) > 100:
        raise ValidationError("cron schedule is too long")
    try:
        croniter(expr)
    except (ValueError, KeyError) as exc:
        raise ValidationError(f"invalid cron schedule: {exc}") from None


def next_cron_occurrence(expr: str, after: datetime) -> datetime:
    """First occurrence strictly after `after` (aware UTC)."""
    return croniter(expr, after).get_next(datetime)


def validate_params(schema: dict[str, dict[str, Any]], values: dict[str, Any]) -> dict[str, Any]:
    """Validate/coerce user-supplied param values against the spec schema.

    Returns the full param dict (defaults filled in). Raises ValidationError.
    """
    validated: dict[str, Any] = {}
    for name, rules in (schema or {}).items():
        ptype = rules.get("type", "string")
        if ptype not in PARAM_TYPES:
            raise ValidationError(f"param {name!r}: unknown type {ptype!r}")
        supplied = name in (values or {})
        raw = (values or {}).get(name)
        if not supplied or raw is None:
            if "default" not in rules:
                raise ValidationError(f"param {name!r} is required")
            validated[name] = rules["default"]
            continue
        validated[name] = _coerce(name, ptype, raw, rules)

    unknown = set(values or {}) - set(schema or {})
    if unknown:
        raise ValidationError(f"unknown parameters: {', '.join(sorted(unknown))}")
    return validated


def _coerce(name: str, ptype: str, raw: Any, rules: dict[str, Any]) -> Any:
    if ptype == "int":
        if isinstance(raw, bool) or not isinstance(raw, int):
            try:
                raw = int(str(raw))
            except ValueError:
                raise ValidationError(f"param {name!r} must be an integer") from None
        _check_range(name, raw, rules)
        return raw
    if ptype == "float":
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            try:
                raw = float(str(raw))
            except ValueError:
                raise ValidationError(f"param {name!r} must be a number") from None
        _check_range(name, float(raw), rules)
        return raw
    if ptype == "password":
        if not isinstance(raw, str):
            raise ValidationError(f"param {name!r} must be a string")
        return raw
    if ptype == "date":
        if not isinstance(raw, str):
            raise ValidationError(f"param {name!r} must be an ISO date (YYYY-MM-DD)")
        try:
            datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            raise ValidationError(f"param {name!r} must be an ISO date (YYYY-MM-DD)") from None
        return raw
    # string
    if not isinstance(raw, str):
        raise ValidationError(f"param {name!r} must be a string")
    max_length = rules.get("max_length")
    if max_length is not None and len(raw) > max_length:
        raise ValidationError(f"param {name!r} exceeds {max_length} characters")
    return raw


def _check_range(name: str, value: float, rules: dict[str, Any]) -> None:
    minimum = rules.get("min")
    maximum = rules.get("max")
    if minimum is not None and value < minimum:
        raise ValidationError(f"param {name!r} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValidationError(f"param {name!r} must be <= {maximum}")


def default_params(schema: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Default param values for a schema (used when provisioning rows)."""
    return {
        name: rules.get("default") for name, rules in (schema or {}).items() if "default" in rules
    }


class JobRegistry:
    """Process-wide registry of job specs. Services register at import time."""

    def __init__(self) -> None:
        self._specs: dict[str, JobSpec] = {}

    def register(self, spec: JobSpec) -> Callable[[JobHandler], JobHandler]:
        """Decorator-style registration: `@job_registry.register(JobSpec(...))`."""
        if spec.scope not in ("workspace", "global"):
            raise ValueError(f"job {spec.key!r}: scope must be 'workspace' or 'global'")
        validate_cron_schedule(spec.schedule)

        def decorator(fn: JobHandler) -> JobHandler:
            if spec.key in self._specs:
                raise ValueError(f"duplicate job registration for key {spec.key!r}")
            spec.handler = fn
            self._specs[spec.key] = spec
            return fn

        return decorator

    def get(self, key: str) -> JobSpec | None:
        return self._specs.get(key)

    def all(self) -> list[JobSpec]:
        return list(self._specs.values())

    def reset(self) -> None:
        self._specs.clear()


job_registry = JobRegistry()


def register_builtin_jobs() -> None:
    """Import built-in job modules so their registrations run exactly once."""
    from src.jobs import builtin  # noqa: F401  (import side effect: registration)
