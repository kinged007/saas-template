from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol


@dataclass
class RunSpec:
    workspace_id: str
    agent_id: str
    conversation_id: str
    session_id: str | None = None
    model: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 600


@dataclass
class RunHandle:
    run_id: str
    workdir: str
    spec: RunSpec


@dataclass
class AgentEvent:
    type: str
    data: dict


class RunnerService(Protocol):
    async def provision(self, spec: RunSpec) -> RunHandle: ...
    async def execute(self, handle: RunHandle, payload: dict) -> AsyncIterator[AgentEvent]: ...
    async def close(self, handle: RunHandle) -> None: ...
