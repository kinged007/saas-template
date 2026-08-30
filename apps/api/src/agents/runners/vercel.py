from __future__ import annotations

import logging
from typing import AsyncIterator

from src.agents.runners.base import AgentEvent, RunHandle, RunSpec
from src.agents.runners.local import LocalTmpRunner

logger = logging.getLogger(__name__)

# Phase 6 stub: falls back to LocalTmpRunner until Vercel Sandbox creds + SDK are wired.
# Keeps the RunnerService contract stable so handler code never branches on driver.


class VercelSandboxRunner(LocalTmpRunner):  # type: ignore[misc]
    """Stub Vercel runner — delegates to LocalTmpRunner until real sandbox is implemented."""

    async def provision(self, spec: RunSpec) -> RunHandle:
        logger.info("VercelSandboxRunner stub: delegating provision to LocalTmpRunner")
        return await super().provision(spec)

    async def execute(self, handle: RunHandle, payload: dict) -> AsyncIterator[AgentEvent]:
        # Phase 6 will replace with real Vercel Sandbox exec (snapshot/restore, FS+exec APIs).
        async for ev in super().execute(handle, payload):
            yield ev

    async def close(self, handle: RunHandle) -> None:
        await super().close(handle)
