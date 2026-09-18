"""Process-level counters with a Prometheus text exposition renderer.

Stdlib only: no prometheus_client dependency. Counters live in memory (reset
on restart — acceptable for a template; production scrapes frequently enough
that restart resets are visible as counter resets, which Prometheus handles).
Label values must be bounded-cardinality (route templates, not raw ids).
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}


def inc(name: str, value: float = 1.0, **labels: str) -> None:
    """Increment counter `name` (label set given as kwargs)."""
    key = (name, tuple(sorted(labels.items())))
    with _lock:
        _counters[key] = _counters.get(key, 0.0) + value


def observe_request(*, method: str, path: str, status: int) -> None:
    inc("http_requests_total", method=method, path=path, status=str(status))


def observe_job_run(*, key: str, status: str) -> None:
    inc("job_runs_total", key=key, status=status)


def observe_webhook_delivery(*, outcome: str) -> None:
    inc("webhook_deliveries_total", outcome=outcome)


def render_prometheus() -> str:
    """Render all counters in Prometheus text exposition format."""
    with _lock:
        items = sorted(_counters.items())
    by_name: dict[str, list[str]] = {}
    for (name, label_items), value in items:
        labels = ",".join(f'{k}="{v}"' for k, v in label_items)
        sample = f"{name}{{{labels}}} {value:g}" if labels else f"{name} {value:g}"
        by_name.setdefault(name, []).append(sample)
    lines: list[str] = []
    for name in sorted(by_name):
        lines.append(f"# TYPE {name} counter")
        lines.extend(by_name[name])
    return "".join(f"{line}\n" for line in lines) if lines else ""


def reset() -> None:
    """Clear all counters (tests only)."""
    with _lock:
        _counters.clear()
