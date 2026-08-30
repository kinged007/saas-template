from __future__ import annotations

from src.agents.runners.base import RunnerService
from src.agents.runners.local import LocalTmpRunner
from src.settings import settings


def build_runner() -> RunnerService:
    driver = (settings.agent_runner_driver or "local").lower()
    if driver == "vercel":
        try:
            from src.agents.runners.vercel import VercelSandboxRunner

            return VercelSandboxRunner()  # type: ignore[return-value]
        except Exception:
            # fallback to local if vercel creds missing
            return LocalTmpRunner()  # type: ignore[return-value]
    return LocalTmpRunner()  # type: ignore[return-value]
