from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol


@dataclass
class AgentRequest:
    entity_type: str  # e.g. "chat"
    conversation_id: str
    message_id: str
    agent_id: str
    workspace_id: str
    triggering_user_id: str


@dataclass
class AgentContext:
    request: AgentRequest
    profile: dict | None = None
    session_ref: str | None = None


@dataclass
class AgentEvent:
    type: str  # e.g. "token", "tool_call", "done"
    data: dict


class AgentHandler(Protocol):
    entity_type: str
    queue_subject: str  # e.g. "agents.requests.chat"
    inject_platform_mcp: bool

    async def on_request(self, req: AgentRequest) -> None: ...
    async def collect_context(self, req: AgentRequest) -> AgentContext: ...
    async def execute(self, ctx: AgentContext) -> AsyncIterator[AgentEvent]: ...
    async def retrieve_session_history(self, req: AgentRequest) -> list[dict]: ...
    async def post_process(self, req: AgentRequest, ctx: AgentContext, events: list[AgentEvent], result: dict | None) -> None: ...
    async def pause_for_permission(self, req: AgentRequest, ctx: AgentContext, tool: str, args: dict) -> None: ...
    async def resume(self, req: AgentRequest, decision: dict) -> None: ...
