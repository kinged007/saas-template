#!/usr/bin/env python3
"""Supervisor for `make dev`: starts API + web and guarantees both are
stopped on Ctrl-C / SIGTERM, or when either one exits or crashes.

Why this exists: GNU make runs recipes with SIGINT/SIGQUIT ignored, and
children inherit that, so a plain `trap ... INT` in a Makefile recipe never
fires and a `kill 0` from it is unreliable. This process re-arms signal
handlers (Python can override the inherited ignore), gives each server its
own process group, and kills those groups explicitly (SIGTERM, then SIGKILL
after a grace period) so no orphan keeps listening on :8000 or :5173.

Stdlib only. Run from the repo root.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SERVERS = [
    {
        "name": "api",
        "cwd": os.path.join(ROOT, "apps", "api"),
        "cmd": ["uv", "run", "uvicorn", "src.main:app", "--reload", "--port", "8000"],
    },
    {
        "name": "web",
        "cwd": os.path.join(ROOT, "apps", "web"),
        "cmd": ["npm", "run", "dev"],
    },
]

GRACE_SECONDS = 3.0
HANDLED = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def main() -> int:
    stop_signal = None
    procs = {}

    def handle(sig: int, frame) -> None:
        nonlocal stop_signal
        if stop_signal is None:
            print(f"\nreceived {signal.Signals(sig).name}, stopping servers...")
            stop_signal = sig
        else:
            kill_all(procs, signal.SIGKILL)

    for sig in HANDLED:
        signal.signal(sig, handle)

    exit_code = None
    try:
        for s in SERVERS:
            procs[s["name"]] = subprocess.Popen(s["cmd"], cwd=s["cwd"], start_new_session=True)

        print("==> api on :8000, web on :5173 (open http://localhost:5173) — Ctrl-C stops both")

        while True:
            if stop_signal is not None:
                break
            for name, proc in procs.items():
                status = proc.poll()
                if status is not None:
                    print(f"{name} exited (status {status}), stopping the other...")
                    exit_code = status if status != 0 else exit_code
                    break
            if exit_code is not None:
                break
            time.sleep(0.1)
    except FileNotFoundError as e:
        print(f"error: could not start a server: {e}", file=sys.stderr)
        exit_code = 127
    except Exception as e:
        print(f"error: unexpected failure: {e}", file=sys.stderr)
        exit_code = 1
    finally:
        kill_all(procs, signal.SIGTERM)
        wait_all(procs, GRACE_SECONDS)
        kill_all(procs, signal.SIGKILL)
        wait_all(procs, None)

    if stop_signal is not None:
        return 128 + stop_signal
    return exit_code or 0


def kill_all(procs: dict, sig: int) -> None:
    for name, proc in procs.items():
        if proc.poll() is not None:
            continue
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError, AttributeError):
            try:
                proc.send_signal(sig)
            except Exception:
                pass


def wait_all(procs: dict, timeout: float | None) -> None:
    deadline = None if timeout is None else time.monotonic() + timeout
    while any(p.poll() is None for p in procs.values()):
        if deadline is not None and time.monotonic() >= deadline:
            return
        time.sleep(0.05)


if __name__ == "__main__":
    sys.exit(main())
