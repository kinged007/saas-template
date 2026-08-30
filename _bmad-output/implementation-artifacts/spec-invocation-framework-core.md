---
title: 'Invocation Framework Core (Phase 4)'
type: 'feature'
created: '2026-08-31'
status: 'in-progress'
baseline_commit: 'agents-foundation'
context: ['plans/agent-platform-plan.md Phase 4']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** No durable request/handler pipeline exists — messages cannot wake agents, no isolated runner abstraction, no session store, no streaming fanout.

**Approach:** Add the framework only (no ChatHandler/LLM, no runner impl beyond LocalTmp stub). Reuse NATS JetStream durable `agents.requests.{entity}` + transient `agents.run.event / agents.permission.event`, `Handler`/`Runner` Protocols, filesystem `SessionStore`, router workflow on `conversations.message.created`.

## Boundaries & Constraints

**Always:**
- Reuse `WorkflowRegistry` + `EventBus` contracts; durable subjects load-balanced, fanout every-replica pushes via `ConnectionManager`.
- Idempotency key `(conversation_id, message_id, agent_id)` for router deduplication (in-memory set + DB check if needed — keep simple: publish once per agent participant).
- Session artifact never touches `messages`; handler-owned directory under `agent_runner_root / workspace / agent / conversation / session_id`.
- Tool secrets `agent:{id}:*` resolved host-side only inside `RunnerService`, never logged.

**Ask First:**
- If router needs `conversations.entity_type` now — plan says Phase 4+5 adds it, but for v1 hardcode `"chat"` as entity_type (all conversations are chat until task entity ships). Propose before adding column this phase.

**Never:**
- No Pydantic AI / LLM loop, no Vercel SDK, no pgvector/memory, no platform MCP, no permission-request table — all Phases 5–8.
- No raw `subprocess` outside `RunnerService`; no DB credentials inside runner payload.

## I/O & Edge-Case Matrix

| Scenario | Expected |
|---|---|
| Message in conversation with 2 active agents → router | 2 publishes to `agents.requests.chat`, each payload `{entity_type, conversation_id, message_id, agent_id, workspace_id, triggering_user_id}` |
| Conversation with no agent participants | No publish |
| Inactive agent participant | Skipped |
| Runner provision/execute/close contract | Stub LocalTmpRunner creates tmpdir, echoes events, teardown deletes |
| SessionStore write/read | `write(workspace, agent, conversation, session_id, history)` → JSON; `read` returns same; missing → None |
| `agents.run.event` transient fanout | Every replica `push_many` to participant user_ids |

</frozen-after-approval>

## Code Map

- `apps/api/src/events/subjects.py` — add `AGENTS_REQUEST_PREFIX="agents.requests."`, `AGENTS_REQUEST_CHAT="agents.requests.chat"`, `AGENTS_RUN_EVENT="agents.run.event"`, `AGENTS_PERMISSION_EVENT="agents.permission.event"`; add to `TRANSIENT_SUBJECTS` (run/permission) and `ALL`.
- `apps/api/src/events/nats.py` — extend `STREAM_SUBJECTS` with `f"{Subjects.AGENTS}.>"` (i.e. `agents.>`)
- `apps/api/src/agents/handlers/base.py` — NEW `AgentRequest`, `AgentContext`, `AgentEvent`, `AgentHandler` Protocol (entity_type, queue_subject, inject_platform_mcp, on_request/collect_context/execute/retrieve_session_history/post_process/pause_for_permission/resume)
- `apps/api/src/agents/runners/base.py` — NEW `RunSpec`, `RunHandle`, `RunnerService` Protocol (provision/execute/close)
- `apps/api/src/agents/runners/local.py` — NEW `LocalTmpRunner` minimal stub (tmp dir under `settings.agent_runner_root`, future gVisor hook)
- `apps/api/src/agents/sessions/store.py` — NEW `SessionStore` (filesystem JSON, keyed by workspace/agent/conversation/session_id)
- `apps/api/src/agents/registry.py` — NEW `handler_registry: dict[str, AgentHandler]` wiring helper
- `apps/api/src/workflows/__init__.py` — router workflow: subscribe `CONVERSATION_MESSAGE_CREATED` durable → load agent participants (active, `participant_type=agent`), publish `AGENTS_REQUEST_CHAT`; fanout for `AGENTS_RUN_EVENT → connection_manager.push_many`
- `apps/api/src/settings.py` — ensure `agent_runner_root`, `agent_runner_driver`, `agent_mcp_enabled` already or add here (shared with Phase 3)
- `apps/api/alembic/versions/` — NO migration this phase (router uses existing tables); `conversations.entity_type` + `agent_session_ref` deferred to Phase 5
- `apps/api/tests/test_invocation_framework.py` — NEW: subjects in ALL/TRANSIENT, SessionStore roundtrip, Runner provision/close, router publishes per agent / skips inactive

## Tasks & Acceptance

- [ ] subjects + STREAM_SUBJECTS
- [ ] handler/runner/session protocols + stubs + registry
- [ ] router workflow + run-event fanout
- [ ] settings wiring if not in Phase 3
- [ ] tests

**AC:**
- `CONVERSATION_MESSAGE_CREATED` with agent participants → `AGENTS_REQUEST_CHAT` observed on bus (InProcess), one per active agent.
- No-agent conversation → no publish.
- `SessionStore.write` then `read` roundtrips; Runner `provision` creates dir, `close` removes.
- `AGENTS_RUN_EVENT` payload reaches `ConnectionManager.push_many` (mock verified).

## Verification

- `uv run pytest tests/test_invocation_framework.py -q && uv run pytest -q`
- `uv run alembic upgrade head` (no-op this phase, but still head=0008)
- Manual: send message in agent conversation → logs show router publish; InProcess bus delivers to stub handler.
