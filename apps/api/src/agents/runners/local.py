from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path
from typing import AsyncIterator

from src.agents.runners.base import AgentEvent, RunHandle, RunSpec
from src.settings import settings


class LocalTmpRunner:
    """Minimal local runner: tmp dir per run, no real LLM execution yet.

    Future: subprocess with gVisor (runsc) when available, network isolation,
    resource caps. For Phase 4 this only proves the provision/close contract.
    """

    async def provision(self, spec: RunSpec) -> RunHandle:
        root = Path(settings.agent_runner_root)
        root.mkdir(parents=True, exist_ok=True)
        workdir = tempfile.mkdtemp(prefix=f"agent-{spec.agent_id[:8]}-", dir=str(root))
        return RunHandle(run_id=str(uuid.uuid4()), workdir=workdir, spec=spec)

    async def execute(self, handle: RunHandle, payload: dict) -> AsyncIterator[AgentEvent]:
        # Stub: emit a single done event; real handler (Phase 5+) will yield tokens.
        yield AgentEvent(type="done", data={"run_id": handle.run_id, "workdir": handle.workdir})
        # keep as async generator
        if False:
            yield  # pragma: no cover

    async def close(self, handle: RunHandle) -> None:
        try:
            shutil.rmtree(handle.workdir, ignore_errors=True)
        except Exception:
            pass
