from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import AsyncIterator

from sqlalchemy import select

from src.agents.handlers.base import AgentContext, AgentEvent, AgentRequest
from src.db.session import SessionFactory
from src.events.publisher import publish_audit, publish_event
from src.events.subjects import Subjects
from src.settings import settings

logger = logging.getLogger(__name__)


def _cost_cents_from(usage: dict | None) -> Decimal:
    """Cost in cents from the provider-reported USD cost (OpenRouter reports
    `usage.cost` in the response); 0 when the provider did not report one."""
    cost_usd = (usage or {}).get("cost_usd")
    if cost_usd is None:
        return Decimal("0")
    try:
        return (Decimal(str(cost_usd)) * 100).quantize(Decimal("0.0001"))
    except Exception:
        return Decimal("0")


@dataclass
class AgentDeps:
    workspace_id: str
    agent_id: str
    triggering_user_id: str
    agent_perms: set[str]
    user_perms: set[str]


class ChatHandler:
    """Phase 5+ handler: pydantic-ai agent loop + SessionStore enrichment."""

    entity_type = "chat"
    queue_subject = Subjects.AGENTS_REQUEST_CHAT
    inject_platform_mcp = True

    def __init__(self, bus=None, secret_store=None) -> None:
        self._bus = bus
        self._secret_store = secret_store

    # ---------------------------------------------------------------- entry

    async def on_request(self, req: AgentRequest) -> None:
        started = time.monotonic()
        ctx: AgentContext | None = None
        try:
            ctx = await self.collect_context(req)
            result: dict | None = None
            events: list[AgentEvent] = []
            paused = False
            async for ev in self.execute(ctx):
                if ev.type == "permission_request":
                    events.append(ev)
                    paused = True
                    continue
                events.append(ev)
                try:
                    await publish_event(
                        self._bus,
                        Subjects.AGENTS_RUN_EVENT,
                        {
                            "workspace_id": req.workspace_id,
                            "conversation_id": req.conversation_id,
                            "agent_id": req.agent_id,
                            "message_id": req.message_id,
                            "event": {"type": ev.type, "data": ev.data},
                        },
                        transient=True,
                    )
                except Exception:
                    logger.exception("failed to publish agents.run.event for %s", req.message_id)
            if paused:
                try:
                    await publish_event(
                        self._bus,
                        Subjects.AGENTS_PERMISSION_EVENT,
                        {
                            "workspace_id": req.workspace_id,
                            "conversation_id": req.conversation_id,
                            "agent_id": req.agent_id,
                            "message_id": req.message_id,
                            "events": [e.data for e in events],
                        },
                        transient=True,
                    )
                except Exception:
                    pass
                return
            result = {"events": [e.data for e in events]}
            await self.post_process(req, ctx, events, result, started=started)
        except Exception:
            logger.exception("ChatHandler on_request failed for %s", req.message_id)
            # publish error so frontend can show failure
            try:
                await publish_event(
                    self._bus,
                    Subjects.AGENTS_RUN_EVENT,
                    {
                        "workspace_id": req.workspace_id,
                        "conversation_id": req.conversation_id,
                        "agent_id": req.agent_id,
                        "message_id": req.message_id,
                        "event": {"type": "error", "data": {"message": "agent execution failed"}},
                    },
                    transient=True,
                )
            except Exception:
                pass
            # The run never reached post_process — still record a failed usage row
            # so cost/usage monitoring sees every attempted run. Best-effort.
            try:
                await self._record_usage(
                    req,
                    model=(ctx.model if ctx is not None else None) or settings.agent_default_model or "",
                    status="error",
                    usage=getattr(ctx, "_usage", None) if ctx is not None else None,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    tool_calls_count=0,
                )
            except Exception:
                logger.warning("failed to record error usage row for %s", req.message_id, exc_info=True)

    # ---------------------------------------------------------------- phases

    async def collect_context(self, req: AgentRequest) -> AgentContext:
        """Load profile, recent history, resolve model, load session_ref + env secrets."""
        async with SessionFactory() as session:
            from src.models.agent import Agent
            from src.models.conversation import Conversation, ConversationParticipant, Message
            from src.models.workspace_setting import WorkspaceSetting

            agent = await session.get(Agent, req.agent_id)
            profile = None
            session_ref: str | None = None
            if agent is not None:
                # sanity: workspace match (handler never trusts bus payload alone)
                if agent.workspace_id != req.workspace_id:
                    profile = None
                else:
                    profile = {
                        "id": agent.id,
                        "name": agent.name,
                        "system_prompt": agent.system_prompt,
                        "model": agent.model,
                        "temperature": agent.temperature,
                        "max_tokens": agent.max_tokens,
                    }
                    # load per-participant session_ref (unique per agent in this conversation)
                    res = await session.execute(
                        select(ConversationParticipant.agent_session_ref).where(
                            ConversationParticipant.conversation_id == req.conversation_id,
                            ConversationParticipant.participant_type == "agent",
                            ConversationParticipant.participant_id == req.agent_id,
                        )
                    )
                    row = res.scalar_one_or_none()
                    # scalar may be string or wrapped
                    if row is not None:
                        session_ref = row if isinstance(row, str) else str(row)

            # last 20 messages as context (cheap, good enough for Phase 5)
            hist: list[dict] = []
            if req.conversation_id:
                res = await session.execute(
                    select(Message)
                    .where(Message.conversation_id == req.conversation_id)
                    .order_by(Message.created_at.desc())
                    .limit(20)
                )
                msgs = list(reversed(list(res.scalars().all())))
                for m in msgs:
                    hist.append({"sender_type": m.sender_type, "sender_id": m.sender_id, "body": m.body})

            # Phase 7: top-k memories for the triple (workspace, agent, user).
            # Recency-only when vector_enabled is off (dev/embedded); embedding
            # similarity kick in when a provider exists (see MemoryStore.retrieve).
            memories: list[dict] = []
            if req.triggering_user_id:
                try:
                    from src.agents.memory import MemoryStore

                    memories = await MemoryStore().retrieve(
                        req.workspace_id, req.agent_id, req.triggering_user_id, limit=10
                    )
                except Exception:
                    logger.warning(
                        "memory retrieval failed for %s/%s",
                        req.workspace_id,
                        req.agent_id,
                        exc_info=True,
                    )

            # model fallback: agent.model → workspace agents.default_model → settings.agent_default_model
            model = profile.get("model") if profile else None
            if not model:
                res = await session.execute(
                    select(WorkspaceSetting).where(
                        WorkspaceSetting.workspace_id == req.workspace_id,
                        WorkspaceSetting.key == "agents.default_model",
                    )
                )
                row = res.scalar_one_or_none()
                if row is not None and isinstance(row.value, str) and row.value.strip():
                    model = row.value.strip()
                elif row is not None and isinstance(row.value, dict) and isinstance(row.value.get("value"), str):
                    v = row.value["value"]
                    if isinstance(v, str) and v.strip():
                        model = v
            if not model and settings.agent_default_model:
                model = settings.agent_default_model

            # agent role perms (deny if role_id null) + triggering user perms for intersection
            agent_perms: set[str] = set()
            user_perms: set[str] = set()
            if agent is not None and agent.workspace_id == req.workspace_id:
                if agent.role_id:
                    from src.models.workspace import Role

                    role = await session.get(Role, agent.role_id)
                    if role is not None:
                        agent_perms = set(role.permissions or [])
                        if "*" in agent_perms:
                            agent_perms.add("*")
                if req.triggering_user_id:
                    from src.services.workspaces import WorkspaceService

                    svc = WorkspaceService(session)
                    try:
                        mem = await svc.get_membership(req.workspace_id, req.triggering_user_id)
                        if mem is not None:
                            _, r = mem
                            user_perms = set(r.permissions or [])
                            if "*" in user_perms:
                                user_perms.add("*")
                    except Exception:
                        pass

            # env secrets for this agent (host-side only, never logged)
            env: dict[str, str] = {}
            if self._secret_store is not None:
                try:
                    prefix = f"agent:{req.agent_id}:"
                    records = await self._secret_store.list_for_workspace(req.workspace_id, prefix=prefix)
                    for r in records:
                        k = r.key[len(prefix):] if r.key.startswith(prefix) else r.key
                        # need decrypt: get each secret value via get()
                        rec = await self._secret_store.get(workspace_id=req.workspace_id, key=r.key)
                        if rec is not None and rec.value:
                            env[k] = rec.value
                except Exception:
                    logger.warning("failed to load agent env for %s", req.agent_id, exc_info=True)

        ctx = AgentContext(request=req, profile=profile, session_ref=session_ref, history=hist, memories=memories, model=model, env=env)  # type: ignore
        object.__setattr__(ctx, "_agent_perms", agent_perms)  # type: ignore
        object.__setattr__(ctx, "_user_perms", user_perms)  # type: ignore
        return ctx

    def _build_model(self, model: str | None, env: dict[str, str]):
        name = (model or "").strip() or settings.agent_default_model or "openrouter/free"
        if name == "test" or settings.environment == "test":
            try:
                from pydantic_ai.models.test import TestModel

                return TestModel()
            except Exception:
                return name
        if "/" in name and ":" not in name:
            if name.startswith("openrouter/"):
                return f"openrouter:{name}"
            if name.startswith("ollama/"):
                return name  # pydantic-ai has ollama provider builtin
            return name
        return name

    async def execute(self, ctx: AgentContext) -> AsyncIterator[AgentEvent]:
        profile = ctx.profile or {}
        agent_perms: set[str] = getattr(ctx, "_agent_perms", set())  # type: ignore
        user_perms: set[str] = getattr(ctx, "_user_perms", set())  # type: ignore
        deps = AgentDeps(
            workspace_id=ctx.request.workspace_id,
            agent_id=ctx.request.agent_id,
            triggering_user_id=ctx.request.triggering_user_id,
            agent_perms=agent_perms,
            user_perms=user_perms,
        )
        model_name = self._build_model(ctx.model, ctx.env or {})
        is_test = not isinstance(model_name, str)
        model_obj: object = model_name if is_test else model_name

        if not is_test:
            from src.agents.llm import _select_key  # type: ignore

            if not _select_key(model_name if isinstance(model_name, str) else "", ctx.env or {}):  # type: ignore
                yield AgentEvent(type="error", data={"message": "No LLM API key configured for this agent. Set OPENROUTER_API_KEY / OPENAI_API_KEY in agent secrets or server env."})
                yield AgentEvent(type="done", data={})
                return

        tools: list = []
        toolsets: list = []
        if self.inject_platform_mcp:
            try:
                from src.mcp.platform.registry import build_tools

                tools = build_tools(deps)
            except Exception:
                logger.exception("platform tool registry failed")

        system_prompt = profile.get("system_prompt")
        if ctx.memories:
            block = "\n".join(f"- ({m.get('kind')}) {m.get('content')}" for m in ctx.memories)
            system_prompt = (system_prompt or "").strip() + f"\n\nRelevant memory:\n{block}"

        prompt = ""
        for h in reversed(ctx.history or []):
            if h.get("sender_type") != "agent" and (h.get("body") or "").strip():
                prompt = h["body"]
                break
        if not prompt:
            prompt = "hello"

        try:
            from pydantic_ai import Agent as PydAgent
            from pydantic_ai.tools import DeferredToolRequests

            test_agent = getattr(ctx, "_test_agent", None)  # type: ignore
            if test_agent is not None:
                agent = test_agent
            else:
                # pydantic-ai requires a str; None (prompt-less agents) crashes
                # the constructor, so only pass it when non-empty.
                prompt_kwargs = {"system_prompt": system_prompt} if system_prompt else {}
                agent = PydAgent(
                    model_obj,  # type: ignore[arg-type]
                    output_type=str | DeferredToolRequests,  # type: ignore[arg-type]
                    deps_type=AgentDeps,
                    tools=tools,
                    toolsets=toolsets or None,
                    retries=1,
                    **prompt_kwargs,
                )
            run_result = await agent.run(
                prompt,
                deps=deps,
                # Ask OpenRouter to return usage accounting (incl. its
                # provider-reported `cost`) in the response.
                model_settings=(
                    {"openrouter_usage": {"include": True}}
                    if isinstance(model_name, str) and model_name.lower().startswith("openrouter")
                    else None
                ),
            )  # type: ignore[arg-type]
            # Phase 9: keep the run's token usage + provider-reported cost for
            # the post_process usage row (pydantic-ai surfaces cost as USD).
            try:
                usage = getattr(run_result, "usage", None)
                if usage is not None:
                    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                    cost = getattr(usage, "cost", None)
                    stash: dict = {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0)
                        or (input_tokens + output_tokens),
                    }
                    if cost is not None:
                        stash["cost_usd"] = float(cost)
                    object.__setattr__(ctx, "_usage", stash)
            except Exception:
                logger.debug("could not extract usage for %s", ctx.request.message_id, exc_info=True)
            output = run_result.output
            if isinstance(output, DeferredToolRequests):
                for call in output.approvals:
                    args_summary = {}
                    try:
                        args_summary = dict(call.args or {}) if hasattr(call, "args") else {}
                    except Exception:
                        pass
                    await self.pause_for_permission(
                        ctx.request, ctx, tool=call.tool_name, args=args_summary, tool_call_id=call.tool_call_id, message_history=run_result.all_messages(), deferred=output  # type: ignore[attr-defined]
                    )
                    yield AgentEvent(type="permission_request", data={"tool": call.tool_name, "tool_call_id": call.tool_call_id, "args": args_summary})
                # persist pending tool_call parts so inbox shows pending approval
                now = datetime.now(timezone.utc)
                steps: list[dict] = []
                for call in getattr(output, "approvals", []):
                    steps.append({"kind": "tool_call", "title": call.tool_name, "content": str(getattr(call, "args", "")), "status": "pending_approval", "created_at": now.isoformat()})
                if steps:
                    await self._write_session_steps(ctx.request, deps, steps)
                return

            # normal output — token + thinking/tool parts from message history
            for msg in run_result.all_messages():  # type: ignore[attr-defined]
                for part in getattr(msg, "parts", []) or []:
                    kind = getattr(part, "part_kind", "")
                    if kind == "thinking":
                        yield AgentEvent(type="thinking", data={"title": "Thinking", "content": getattr(part, "content", "")})
                    elif kind == "tool-call":
                        yield AgentEvent(type="tool_call", data={"title": getattr(part, "tool_name", "tool"), "content": str(getattr(part, "args", ""))})
                    elif kind == "tool-return":
                        yield AgentEvent(type="tool_result", data={"title": getattr(part, "tool_name", ""), "content": str(getattr(part, "content", ""))})
            text = str(output) if output is not None else ""
            if text.strip():
                yield AgentEvent(type="token", data={"text": text})
            yield AgentEvent(type="done", data={})
            # also persist tool/thinking parts for inbox timeline
            now = datetime.now(timezone.utc)
            steps = []
            for msg in run_result.all_messages():  # type: ignore[attr-defined]
                for part in getattr(msg, "parts", []) or []:
                    kind = getattr(part, "part_kind", "")
                    if kind == "thinking":
                        steps.append({"kind": "thinking", "title": "Thinking", "content": getattr(part, "content", ""), "created_at": now.isoformat()})
                    elif kind == "tool-call":
                        steps.append({"kind": "tool_call", "title": getattr(part, "tool_name", "tool"), "content": str(getattr(part, "args", "")), "created_at": now.isoformat()})
                    elif kind == "tool-return":
                        steps.append({"kind": "tool_result", "title": getattr(part, "tool_name", ""), "content": str(getattr(part, "content", "")), "created_at": now.isoformat()})
            if steps:
                await self._write_session_steps(ctx.request, deps, steps)
        except Exception:
            logger.exception("ChatHandler execute failed")
            try:
                from src.agents.llm import stream_chat

                system_prompt2 = profile.get("system_prompt")
                if ctx.memories:
                    block = "\n".join(f"- ({m.get('kind')}) {m.get('content')}" for m in ctx.memories)
                    system_prompt2 = (system_prompt2 or "").strip() + f"\n\nRelevant memory:\n{block}"
                async for ev in stream_chat(
                    model=ctx.model,
                    env=ctx.env or {},
                    system_prompt=system_prompt2,
                    history=ctx.history or [],
                    temperature=profile.get("temperature"),
                    max_tokens=profile.get("max_tokens"),
                ):
                    # The fallback client reports provider usage (tokens + USD
                    # cost when the provider returns it) on its done event.
                    if ev["type"] == "done" and ev["data"].get("usage"):
                        raw = ev["data"]["usage"]
                        input_tokens = int(raw.get("prompt_tokens") or raw.get("input_tokens") or 0)
                        output_tokens = int(raw.get("completion_tokens") or raw.get("output_tokens") or 0)
                        stash = {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "total_tokens": int(raw.get("total_tokens") or 0)
                            or (input_tokens + output_tokens),
                        }
                        if raw.get("cost") is not None:
                            stash["cost_usd"] = float(raw["cost"])
                        object.__setattr__(ctx, "_usage", stash)
                    yield AgentEvent(type=ev["type"], data=ev["data"])
            except Exception:
                yield AgentEvent(type="error", data={"message": "agent execution failed"})

    async def _write_session_steps(self, req: AgentRequest, deps: AgentDeps, steps: list[dict]) -> None:
        async with SessionFactory() as session:
            from src.models.conversation import ConversationParticipant

            res = await session.execute(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == req.conversation_id,
                    ConversationParticipant.participant_type == "agent",
                    ConversationParticipant.participant_id == req.agent_id,
                )
            )
            participant = res.scalar_one_or_none()
            if participant is None:
                return
            session_id = participant.agent_session_ref
            if not session_id:
                session_id = str(uuid.uuid4())
                participant.agent_session_ref = session_id
                await session.commit()
        from src.agents.sessions.store import SessionStore

        store = SessionStore()
        prior = await store.read(req.workspace_id, req.agent_id, req.conversation_id, session_id)
        history = list(prior) if prior else []
        history.extend(steps)
        await store.write(req.workspace_id, req.agent_id, req.conversation_id, session_id, history)

    async def retrieve_session_history(self, req: AgentRequest) -> list[dict]:
        if not req.workspace_id or not req.conversation_id or not req.agent_id:
            return []
        # session_id is the participant's agent_session_ref; if none, no history yet
        async with SessionFactory() as session:
            from src.models.conversation import ConversationParticipant

            res = await session.execute(
                select(ConversationParticipant.agent_session_ref).where(
                    ConversationParticipant.conversation_id == req.conversation_id,
                    ConversationParticipant.participant_type == "agent",
                    ConversationParticipant.participant_id == req.agent_id,
                )
            )
            ref = res.scalar_one_or_none()
            if isinstance(ref, tuple):
                ref = ref[0]
            session_id = ref if isinstance(ref, str) and ref else None
        if not session_id:
            return []
        from src.agents.sessions.store import SessionStore

        store = SessionStore()
        data = await store.read(req.workspace_id, req.agent_id, req.conversation_id, session_id)
        return data or []

    async def post_process(
        self,
        req: AgentRequest,
        ctx: AgentContext,
        events: list[AgentEvent],
        result: dict | None,
        *,
        started: float | None = None,
    ) -> None:
        """Persist final assistant reply, update session_ref + SessionStore, audit, push."""
        # Compose final text from token events; LLM errors land as a visible
        # agent message so misconfiguration is actionable in the thread.
        tokens = [e.data.get("text", "") for e in events if e.type == "token"]
        errors = [e for e in events if e.type == "error"]
        if tokens:
            body = "".join(tokens).strip()
        elif errors:
            body = errors[-1].data.get("message") or "Agent execution failed."
        else:
            body = "…"

        # One timestamp anchors the whole turn: the response message AND any
        # parts written to SessionStore share this clock, so the frontend can
        # merge parts (thinking/tool calls, written earlier in the run) and the
        # reply into a single chronological thread.
        from datetime import datetime, timezone

        response_at = datetime.now(timezone.utc)

        async with SessionFactory() as session:
            from src.models.agent import Agent
            from src.models.agent_usage import AgentUsage
            from src.models.conversation import Conversation, ConversationParticipant, Message

            agent = await session.get(Agent, req.agent_id)
            if agent is None or agent.workspace_id != req.workspace_id:
                logger.warning("post_process: agent %s not found in workspace %s", req.agent_id, req.workspace_id)
                return
            conv = await session.get(Conversation, req.conversation_id)
            if conv is None or conv.workspace_id != req.workspace_id:
                logger.warning("post_process: conversation %s not found", req.conversation_id)
                return
            # The triggering user message — used for memory extraction below.
            trigger_msg = await session.get(Message, req.message_id)

            # Persist agent message — the final reply. Thinking/tool-call parts
            # live in SessionStore (written mid-run with their own timestamps);
            # the reply is never duplicated as a session step.
            msg = Message(
                conversation_id=req.conversation_id,
                sender_type="agent",
                sender_id=req.agent_id,
                sender_user_id=None,
                sender_agent_id=req.agent_id,
                body=body,
                created_at=response_at,
            )
            session.add(msg)
            await session.flush()

            # Session management: create/rotate agent_session_ref if missing
            res = await session.execute(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == req.conversation_id,
                    ConversationParticipant.participant_type == "agent",
                    ConversationParticipant.participant_id == req.agent_id,
                )
            )
            participant = res.scalar_one_or_none()
            session_id = None
            if participant is not None:
                session_id = participant.agent_session_ref
                if not session_id:
                    session_id = str(uuid.uuid4())
                    participant.agent_session_ref = session_id
            else:
                # agent not participant — shouldn't happen (router filters) but be defensive
                session_id = str(uuid.uuid4())

            # SessionStore parts: thinking / tool calls / outcomes only — the
            # final reply is the message above and is NOT repeated here. No
            # such parts exist yet (tool loop is Phase 8); when handlers start
            # yielding tool_call/thinking events they will be appended here
            # with their own created_at, ordered before response_at.
            steps: list[dict] = []
            # Append to history: keep prior steps + this turn (only when parts exist)
            from src.agents.sessions.store import SessionStore as _Store

            if steps and session_id:
                store = _Store()
                prior = await store.read(req.workspace_id, req.agent_id, req.conversation_id, session_id)
                history = list(prior) if prior else []
                history.extend(steps)
                await store.write(req.workspace_id, req.agent_id, req.conversation_id, session_id, history)

            # bump conversation preview
            from src.services.conversations import _plain_preview

            conv.last_message_at = response_at
            conv.last_message_preview = _plain_preview(body)

            # Phase 9: exactly one usage row per completed run, in the same
            # transaction as the reply message. Runs paused on a permission
            # request never reach post_process and record nothing (they are
            # not complete); resumed runs go through execute again.
            model_name = (ctx.model or "").strip() or settings.agent_default_model or ""
            usage = getattr(ctx, "_usage", None) or {}
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            session.add(
                AgentUsage(
                    workspace_id=req.workspace_id,
                    agent_id=req.agent_id,
                    user_id=req.triggering_user_id,
                    conversation_id=req.conversation_id,
                    message_id=req.message_id,
                    model=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=int(usage.get("total_tokens") or 0)
                    or (input_tokens + output_tokens),
                    cost_cents=_cost_cents_from(usage),
                    latency_ms=int((time.monotonic() - started) * 1000) if started else 0,
                    tool_calls_count=sum(1 for e in events if e.type == "tool_call"),
                    status="error" if any(e.type == "error" for e in events) else "success",
                )
            )

            await session.commit()
            await session.refresh(msg)

            sender_name = agent.name
            sender_avatar = agent.avatar

            # publish agent message live fanout so thread updates without reload
            try:
                await publish_event(
                    self._bus,
                    Subjects.CONVERSATION_MESSAGE_LIVE,
                    {
                        "workspace_id": req.workspace_id,
                        "conversation_id": req.conversation_id,
                        "message_id": msg.id,
                        "sender_id": req.agent_id,
                        "sender_type": "agent",
                        "sender_name": sender_name,
                        "sender_avatar_url": sender_avatar,
                        "body": msg.body,
                        "body_preview": body[:200],
                        "created_at": msg.created_at.isoformat() if msg.created_at else None,
                    },
                    transient=True,
                )
            except Exception:
                logger.exception("failed to publish agent message live")

            # also durable notification pointer for mention semantics deferred — skip for now (agent reply is implicit)
            try:
                await publish_audit(
                    self._bus,
                    workspace_id=req.workspace_id,
                    resource_type="message",
                    resource_id=msg.id,
                    action="message.created",
                    actor_user_id=None,
                    details={"conversation_id": req.conversation_id, "agent_id": req.agent_id},
                )
            except Exception:
                pass

        # Phase 7: extract durable memories from this turn and upsert them under
        # the (workspace, agent, user) triple, then prune per triple. Best-effort:
        # extraction failure (no LLM key, network) must never break the reply.
        try:
            if req.triggering_user_id:
                user_text = ""
                if trigger_msg is not None and trigger_msg.body:
                    user_text = trigger_msg.body
                transcript = f"{user_text}\n\n{body}".strip()
                if transcript:
                    from src.agents.llm import extract_memories
                    from src.agents.memory import MemoryStore

                    items = await extract_memories(
                        model=ctx.model, env=ctx.env or {}, transcript=transcript
                    )
                    if items:
                        store = MemoryStore()
                        await store.upsert_many(
                            req.workspace_id,
                            req.agent_id,
                            req.triggering_user_id,
                            req.conversation_id,
                            items,
                        )
                        await store.prune(req.workspace_id, req.agent_id, req.triggering_user_id)
        except Exception:
            logger.warning(
                "memory extraction failed for %s/%s",
                req.workspace_id,
                req.agent_id,
                exc_info=True,
            )

    async def _record_usage(
        self,
        req: AgentRequest,
        *,
        model: str,
        status: str,
        usage: dict | None = None,
        latency_ms: int,
        tool_calls_count: int,
    ) -> None:
        from src.models.agent_usage import AgentUsage

        input_tokens = int((usage or {}).get("input_tokens") or 0)
        output_tokens = int((usage or {}).get("output_tokens") or 0)
        async with SessionFactory() as session:
            # post_process may have committed its row before failing — never
            # double-record a run.
            existing = await session.execute(
                select(AgentUsage.id)
                .where(
                    AgentUsage.message_id == req.message_id,
                    AgentUsage.agent_id == req.agent_id,
                )
                .limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                return
            session.add(
                AgentUsage(
                    workspace_id=req.workspace_id,
                    agent_id=req.agent_id,
                    user_id=req.triggering_user_id,
                    conversation_id=req.conversation_id,
                    message_id=req.message_id,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=int((usage or {}).get("total_tokens") or 0)
                    or (input_tokens + output_tokens),
                    cost_cents=_cost_cents_from(usage),
                    latency_ms=latency_ms,
                    tool_calls_count=tool_calls_count,
                    status=status,
                )
            )
            await session.commit()

    async def pause_for_permission(self, req: AgentRequest, ctx: AgentContext, tool: str, args: dict, tool_call_id: str = "", message_history=None, deferred=None) -> None:  # type: ignore[no-untyped-def]
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.agent_permission_ttl)
        async with SessionFactory() as session:
            from src.models.agent_permission import AgentPermissionRequest

            row = AgentPermissionRequest(
                workspace_id=req.workspace_id,
                conversation_id=req.conversation_id,
                agent_id=req.agent_id,
                triggering_user_id=req.triggering_user_id,
                run_message_id=req.message_id,
                tool_name=tool,
                tool_call_id=tool_call_id or str(uuid.uuid4()),
                args_summary=args or {},
                status="pending",
                expires_at=expires_at,
            )
            session.add(row)
            try:
                if message_history is not None:
                    from pydantic_core import to_jsonable_python

                    from pydantic_ai.messages import ModelMessagesTypeAdapter

                    serial = ModelMessagesTypeAdapter.dump_python(message_history)  # type: ignore
                    row.args_summary = {**row.args_summary, "_history": to_jsonable_python(serial)}
            except Exception:
                pass
            await session.commit()

    async def resume(self, req: AgentRequest, decision: dict) -> None:  # pragma: no cover
        return
