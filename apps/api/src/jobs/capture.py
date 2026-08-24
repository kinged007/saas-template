"""Execution log capture: logging records AND stdout/stderr writes.

One root-level logging handler and one stdout/stderr interceptor are
installed for the whole process. Both route captured output to the collector
of the *currently executing job run* via a ContextVar, so concurrent runs in
one process each capture exactly their own output while normal console
output is unaffected.

Sync handlers run via `asyncio.to_thread`, which copies the caller's context,
so the ContextVar routing works across the thread boundary too.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import io
import logging
import sys
import threading
from dataclasses import dataclass, field

# Loggers that would flood run logs with framework noise (SQL echo etc.).
NOISY_LOGGERS = frozenset(
    {
        "sqlalchemy.engine",
        "sqlalchemy.pool",
        "alembic.runtime.migration",
        "asyncio",
    }
)

MAX_ENTRIES_PER_RUN = 5000


@dataclass
class CapturedEntry:
    ts: dt.datetime
    level: str
    message: str


@dataclass
class RunLogCollector:
    """In-memory buffer of one run's captured output."""

    _entries: list[CapturedEntry] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _dropped: int = 0
    # Partial line buffers per stream (stdout writes may arrive in chunks).
    _partial: dict[str, str] = field(default_factory=dict)

    def add(self, level: str, message: str) -> None:
        if not message:
            return
        with self._lock:
            if len(self._entries) >= MAX_ENTRIES_PER_RUN:
                self._dropped += 1
                return
            self._entries.append(CapturedEntry(ts=_now(), level=level or "INFO", message=message))

    def add_stream_chunk(self, stream: str, text: str) -> None:
        """Buffer a raw stdout/stderr write; emits complete lines."""
        level = "ERROR" if stream == "stderr" else "INFO"
        with self._lock:
            buffer = self._partial.get(stream, "") + text
            parts = buffer.split("\n")
            complete, remainder = parts[:-1], parts[-1]
            self._partial[stream] = remainder
            for line in complete:
                if len(self._entries) >= MAX_ENTRIES_PER_RUN:
                    self._dropped += 1
                    continue
                self._entries.append(CapturedEntry(ts=_now(), level=level, message=line))

    def drain(self) -> tuple[list[CapturedEntry], int]:
        """Return pending entries and the running drop count; empties the buffer."""
        with self._lock:
            entries, self._entries = self._entries, []
            dropped, self._dropped = self._dropped, 0
            # Flush any unterminated trailing line so it is not lost.
            for stream, partial in list(self._partial.items()):
                if partial:
                    level = "ERROR" if stream == "stderr" else "INFO"
                    entries.append(CapturedEntry(ts=_now(), level=level, message=partial))
                    self._partial[stream] = ""
        return entries, dropped

    def requeue(self, entries: list[CapturedEntry]) -> None:
        """Put drained-but-unpersisted entries back (write failed; retry later)."""
        if not entries:
            return
        with self._lock:
            self._entries[:0] = entries

    def close(self) -> None:
        pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


_current_collector: contextvars.ContextVar[RunLogCollector | None] = contextvars.ContextVar(
    "job_run_collector", default=None
)


def run_log_collector() -> RunLogCollector | None:
    """The active run's collector in the current context, if any."""
    return _current_collector.get()


def set_run_log_collector(collector: RunLogCollector | None):
    """Bind a collector to this execution context; returns a reset token."""
    return _current_collector.set(collector)


def reset_run_log_collector(token) -> None:
    _current_collector.reset(token)


class CaptureHandler(logging.Handler):
    """Root-level handler that files records into the active run's collector."""

    def emit(self, record: logging.LogRecord) -> None:
        collector = _current_collector.get()
        if collector is None:
            return
        for noisy in NOISY_LOGGERS:
            if record.name == noisy or record.name.startswith(noisy + "."):
                return
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        collector.add(record.levelname, message)


class _CapturedStream(io.TextIOBase):
    """Pass-through wrapper that tees writes into the active run's collector."""

    def __init__(self, original: io.TextIOBase, stream_name: str) -> None:
        self._original = original
        self._stream_name = stream_name

    def write(self, text: str) -> int:
        collector = _current_collector.get()
        if collector is not None and text:
            collector.add_stream_chunk(self._stream_name, text)
        return self._original.write(text)

    def flush(self) -> None:
        self._original.flush()

    def fileno(self) -> int:
        return self._original.fileno()

    def isatty(self) -> bool:
        return self._original.isatty()

    @property
    def encoding(self):  # pragma: no cover - passthrough attribute
        return getattr(self._original, "encoding", None)

    def writable(self) -> bool:
        return True

    def __getattr__(self, name):  # pragma: no cover - delegate everything else
        return getattr(self._original, name)


class RunCapture:
    """Process-wide capture plumbing.

    `install()` is idempotent AND self-healing: host tooling (test runners,
    progress bars, debuggers) may rebind sys.stdout/sys.stderr after we
    wrapped them, silently detaching interception. Each job execution calls
    `install()` again, which re-wraps any stream that is no longer ours so
    the execution window is always fully captured.
    """

    def __init__(self) -> None:
        self.handler: CaptureHandler | None = None
        self._stdout: io.TextIOBase | None = None
        self._stderr: io.TextIOBase | None = None
        self._previous_root_level: int | None = None

    def install(self) -> None:
        root = logging.getLogger()
        if self.handler is None:
            self.handler = CaptureHandler(level=logging.DEBUG)
            # Records are filtered by their ORIGIN logger's effective level
            # before reaching any handler — a host process configured at
            # WARNING would starve run logs of INFO lines. Jobs promise
            # complete logs, so raise the root level for the capture window.
            self._previous_root_level = root.level
            if not root.isEnabledFor(logging.INFO):
                root.setLevel(logging.INFO)
            root.addHandler(self.handler)
        if not isinstance(sys.stdout, _CapturedStream):
            self._stdout = sys.stdout
            sys.stdout = _CapturedStream(sys.stdout, "stdout")  # type: ignore[assignment]
        if not isinstance(sys.stderr, _CapturedStream):
            self._stderr = sys.stderr
            sys.stderr = _CapturedStream(sys.stderr, "stderr")  # type: ignore[assignment]

    def uninstall(self) -> None:
        if self.handler is None:
            return
        root = logging.getLogger()
        root.removeHandler(self.handler)
        if self._previous_root_level is not None:
            root.setLevel(self._previous_root_level)
            self._previous_root_level = None
        self.handler = None
        if isinstance(sys.stdout, _CapturedStream):
            sys.stdout = sys.stdout._original  # noqa: SLF001
        if isinstance(sys.stderr, _CapturedStream):
            sys.stderr = sys.stderr._original  # noqa: SLF001
        self._stdout = None
        self._stderr = None


run_capture = RunCapture()


def install_run_capture() -> None:
    run_capture.install()


def uninstall_run_capture() -> None:
    run_capture.uninstall()
