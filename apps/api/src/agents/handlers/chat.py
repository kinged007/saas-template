from __future__ import annotations

import logging
import uuid
from typing import AsyncIterator

from sqlalchemy import select

from src.agents.handlers.base import AgentContext, AgentEvent, AgentRequest
from src.db.session import SessionFactory
from src.events.publisher import publish_audit, publish_event
from src.events.subjects import Subjects
from src.settings import settings

logger = logging.getLogger(__name__)


class ChatHandler:
    """Phase 5+ handler: real LLM invocation + SessionStore enrichment + final reply persistence.

    Pipeline: on_request → collect_context (profile/history/model/env + Phase 7
    memories) → execute (OpenAI-compatible streaming chat via httpx) →
    post_process (persist final reply as agent message + agent_session_ref +
    SessionStore + live fanout + Phase 7 memory extraction/upsert/prune).
    Tool/MCP loop remains TODO (Phase 8).
    """

    entity_type = "chat"
    queue_subject = Subjects.AGENTS_REQUEST_CHAT
    inject_platform_mcp = False

    def __init__(self, bus=None, secret_store=None) -> None:
        self._bus = bus
        self._secret_store = secret_store

    # ---------------------------------------------------------------- entry

    async def on_request(self, req: AgentRequest) -> None:
        try:
            ctx = await self.collect_context(req)
            result: dict | None = None
            events: list[AgentEvent] = []
            async for ev in self.execute(ctx):
                events.append(ev)
                # stream each token/tool event transient so realtime fanout can push it
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
            result = {"events": [e.data for e in events]}
            await self.post_process(req, ctx, events, result)
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

        return AgentContext(request=req, profile=profile, session_ref=session_ref, history=hist, memories=memories, model=model, env=env)  # type: ignore

    async def execute(self, ctx: AgentContext) -> AsyncIterator[AgentEvent]:
        """Stream a real LLM response (OpenAI-compatible endpoint)."""
        profile = ctx.profile or {}
        try:
            from src.agents.llm import stream_chat

            system_prompt = profile.get("system_prompt")
            if ctx.memories:
                block = "\n".join(f"- ({m.get('kind')}) {m.get('content')}" for m in ctx.memories)
                system_prompt = (system_prompt or "").strip() + f"\n\nRelevant memory:\n{block}"

            async for ev in stream_chat(
                model=ctx.model,
                env=ctx.env or {},
                system_prompt=system_prompt,
                history=ctx.history or [],
                temperature=profile.get("temperature"),
                max_tokens=profile.get("max_tokens"),
            ):
                yield AgentEvent(type=ev["type"], data=ev["data"])
        except Exception:
            logger.exception("ChatHandler execute failed")
            yield AgentEvent(type="error", data={"message": "agent execution failed"})

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

    async def post_process(self, req: AgentRequest, ctx: AgentContext, events: list[AgentEvent], result: dict | None) -> None:
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

    # stubs for permission flow (Phases 5 plan but deferred UI — no-op to satisfy Protocol)
    async def pause_for_permission(self, req: AgentRequest, ctx: AgentContext, tool: str, args: dict) -> None:  # pragma: no cover
        return

    async def resume(self, req: AgentRequest, decision: dict) -> None:  # pragma: no cover
        return
