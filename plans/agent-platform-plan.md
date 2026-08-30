# Agent Platform — High-Level Implementation Plan (v5)

**Goal:** Workspace-scoped AI agents (single `agents` table = identity + profile) invoked through an **extendable handler framework**: `request → handler (dedicated queue) → agent wake → agent execute → logging / metrics / session handling → update handler`. Chat is the first handler; the same pipeline serves any future entity (tasks, etc.) without redesign. Execution runs in isolated runtimes (**local tmp+gVisor** and **Vercel Sandbox** first; Docker/E2B later). Full LLM session history stays OUT of the messaging tables — only final user-visible replies land there; tool calls/thinking live in handler-managed session storage and are **enriched into the chat view on demand**. Tool permission requests pause the agent until a human approves.

> **Scope:** High-level build order + architecture + research. No code.
> **v4 changes vs v3:** chat-handler session enrichment (collapsed thinking/tool steps in thread view; other entities get a "view session log" dialog); `agents.model` nullable; permission-request model + pause/resume flow (agent idles while awaiting approval); runners = local + Vercel Sandbox for v1 (Docker/E2B deferred); workspace settings page with extensible registry (`workspace/registry.ts`) for sandbox credentials + general agent config; Pydantic AI + Vercel AI SDK confirmed complementary.
> **v5 changes vs v4:** platform MCP injection is **handler-controlled** (not automatic) and gated by **agent-assigned workspace roles** (read-only agents supported; MCP verifies agent identity + permissions); platform MCP rebuilt as an **extensible tool registry** (devs add entity tool modules); **agent-specific secrets/env vars** via SecretStore with `agent:{agent_id}:{KEY}` namespacing (UI-managed, per-agent values, injected as runner env); `skills` column added now (skill **ids**, directory deferred).

> **Status update — 2026-08-31 (phases 3–4, specs `spec-workspace-settings.md` + `spec-invocation-framework-core.md`):** Phases 0–4 shipped to current branch (0–2 on `main` + 3–4 this round). Phases 5–11 remain. See §0 for the implementation ledger. Canonical copy of this plan lives at `plans/agent-platform-plan.md` (synced to `~/.commandcode/plans/agent-platform-plan.md`).

---

## 0. Implementation Status — 2026-08-31 (phases 3–4 shipped)

Spec: `_bmad-output/implementation-artifacts/spec-agent-platform-foundation.md` (baseline `98779ee`, shipped). Specs `spec-workspace-settings.md` + `spec-invocation-framework-core.md` (this round). All verification steps passed (§7): `alembic upgrade head` (0008) + downgrade↔upgrade clean, `pytest tests/test_agents.py` (8) + `test_workspace_settings.py` (4) + `test_invocation_framework.py` (4), `npm run build` (tsc + vite).

| Phase | Title | Status | What landed | What remains / next |
|---|---|---|---|---|
| **0** | Permissions & Types | ✅ **Shipped** | `core/permissions.py`: `agent:read`, `agent:manage`, `agent:invoke`, `agent:usage:read` + `ALL_PERMISSIONS` + `permissions_for_role` (owner/admin all; editor/viewer read+invoke; `sync_system_role_permissions` converges existing workspaces). Mirrored in `web/src/permissions.ts` + `PERMISSION_MAP` (`agents: {list/show: read, create/edit/delete: manage}`). `web/src/types.ts`: `Agent` + `AgentSecretInfo`. | `AgentUsageEntry`, `AgentPermissionRequest`, `SessionStep` types still TODO — deferred to Phases 5/9. `agent:invoke`/`agent:usage:read` are seeded but unused (by design). |
| **1** | DB: `0007_agents` | ✅ **Shipped** | `models/agent.py` + `models/__init__.py` + `alembic/versions/0007_agents.py` (table per Code Map: `StringUUID` PK, `workspace_id` idx, `slug`/`name`/`description`/`avatar(300)`/`system_prompt`/`model`/`temperature`/`max_tokens`/`tool_allowlist`/`mcp_servers`/`execution_target`/`role_id` idx/`skills`/`is_active`/`custom_data`/`created_by_user_id`/`updated_by_user_id` + `TimestampMixin`; UQ `uq_agents_workspace_slug` + indexes on `workspace_id, role_id, created_by_user_id, updated_by_user_id`). `settings.py`: `agent_llm_providers` (comma allowlist, empty=any), `agent_default_model`. `schemas/api.py`: `MCPServerSpec` + `AgentCreate`/`AgentUpdate` + `AgentSecretPut`. Secrets: `agent:{agent_id}:{ENV_VAR_NAME}` via `SecretStore` (encrypted, `^[A-Z_][A-Z0-9_]*$`, logical key ≤400, `kind="agent_env"`, write-only, never in `agents` table/response/log). | Pipeline tables **not** in this migration (deferred): `conversations.entity_type`, `conversation_participants.agent_session_ref`, `agent_permission_requests`, `agent_memories`/`agent_usage`; settings `agent_runner_driver`, `agent_runner_root`, `agent_mcp_enabled`, `vector_enabled`, `agent_cost_table`, `agent_permission_ttl` now shipped in Phase 3 `settings.py` (global defaults). |
| **2** | Agents CRUD + Admin UI | ✅ **Shipped** | `services/agents.py` (`AgentService`: slug `^[a-z0-9-]+$` via slugify, workspace-scoped 404, 409 per-WS slug, `role_id` workspace check 422, model allowlist 422, secrets `list/set/delete` + `agents.profile.changed` transient fanout + `agent.created/updated/deleted` + `agent.secret.*` audit). `events/subjects.py`: `AGENT_PROFILE_CHANGED="agents.profile.changed"` (transient). `workflows/__init__.py`: fanout `connection_manager.push_many` to workspace active members. `api/routes/agents.py` + `main.py`: `GET /agents` (read), `POST /agents` 201, `GET/PATCH/DELETE /agents/{id}` (read/manage), `GET/PUT/DELETE /agents/{id}/secrets[/{key}]` (manage, PUT `{value}` upsert, list returns `{key, created_at}` only). `lib/avatar.ts`: `parseAvatarValue` (`url:`/`emoji:` + `https?://`/`data:` heuristic) + `AgentAvatar`. `App.tsx`: `agents` resource (`list/create/edit/:id`, create-before-list). `AppLayout.tsx`: Agents nav `agent:read` gated. `AgentsPage` (ListView, `useCan`), `AgentCreatePage` / `AgentEditPage` (refine `useForm` + `zodResolver`, slug auto-fills until edited, live `AgentAvatar` preview, MCP repeater, role sentinel `__none__→null`, `tool_allowlist` comma input, skills placeholder, Secrets editor write-only). Fixes in this round: MCP block wrapped in `FormField` (was orphaned `FormLabel` → `useFormField` crash), `redirect: "list"` on create (was `false` → stayed on form), `execution_target` → `Select` (`No preference`/`local`/`vercel`, null sentinel), `max_tokens` default `200000`. `tests/test_agents.py`: 8 tests (CRUD, `X-Total-Count`, 409 vs cross-WS 201, 404 isolation, secret 422+masked listing, foreign role 422, editor/viewer 403, missing header 400). | Inbox integration still TODO (agent participants in `ComposeDialog`/`ThreadView` — Phase 5). `skills` remains placeholder until directory exists. Agent list role column is id-prefix only (no name join yet). No `skills` directory, no per-agent usage UI here. |
| **3** | Workspace Settings (registry) | ✅ **Shipped (2026-08-31)** | `models/workspace_setting.py` + `models/__init__.py` + `alembic/versions/0008_workspace_settings.py` (UQ `uq_workspace_settings_workspace_key`, indexes on `workspace_id, updated_by_user_id`). `settings.py`: `agent_runner_driver/local`, `agent_runner_root`, `agent_mcp_enabled`, `vector_enabled`, `agent_cost_table`, `agent_permission_ttl`. `services/workspace_settings.py` (`VALID_KEYS` + `SENSITIVE_KEYS={"agents.sandbox.vercel_token"}`: string/enum/int/bool/secret validation, `workspace:{id}:setting:{key}` via `SecretStore` kind `workspace_setting`, `PUT null` → delete, masked `{has_value}` on read, audit `workspace_setting.updated/deleted` with only `key` in details). `api/routes/workspace_settings.py` + `main.py`: `GET /workspace-settings` (read), `GET/PUT/DELETE /workspace-settings/{key}` (read/update, `PUT {value}`; sensitive write-only, `DELETE` 204, 422 unknown key/enum/type, 404 missing, 403 `workspace:update` required). `web/registry.ts`: `agents-general` + `agents-sandbox` tabs (`workspace:read`, order 60/61). `AgentsGeneralSection.tsx` (default_model/runner/memory TTL) + `AgentsSandboxSection.tsx` (vercel team_id/token write-only + timeout, token `has_value` + Delete, `Checkbox` for bool, `FormField` sentinel `__none__→null`). Tests `tests/test_workspace_settings.py`: 4 (CRUD+422 mask+sensitive has_value+delete, null clears, permission editor 403, cross-workspace isolation). `App.tsx`: two new `/settings/workspace/agents-*` routes. | Follow-up: optional global fallback resolution `agent.model ?? workspace default ?? settings.agent_default_model` (Phase 5 collect_context). |
| **4** | Invocation Framework Core | ✅ **Shipped (2026-08-31)** | `events/subjects.py`: `AGENTS_REQUEST_CHAT="agents.requests.chat"` (durable), `AGENTS_RUN_EVENT` + `AGENTS_PERMISSION_EVENT` (transient), `AGENTS_REQUEST_PREFIX`; `TRANSIENT_SUBJECTS` updated, `ALL` extended. `events/nats.py`: `STREAM_SUBJECTS += agents.>` so durable `agents.requests.*` survives restarts. `agents/handlers/base.py` (AgentRequest/Context/Event, AgentHandler Protocol: `entity_type/queue_subject/inject_platform_mcp`, `on_request/collect_context/execute/retrieve_session_history/post_process/pause_for_permission/resume`), `agents/runners/base.py` (RunSpec/RunHandle/AgentEvent, RunnerService Protocol: provision/execute/close), `agents/runners/local.py` (`LocalTmpRunner`: tmpdir under `agent_runner_root`, stub `done` event, `close` rm), `agents/sessions/store.py` (`SessionStore`: filesystem JSON `root/ws/agent/conv/session.json`, write/read/delete), `agents/registry.py` (`handler_registry` + `register_handler`). `workflows/__init__.py`: wraps `CONVERSATION_MESSAGE_CREATED` to also route to active `agent` participants (durable `AGENTS_REQUEST_CHAT` per agent, skips `is_active=false`, entity_type="chat" hardcoded until `conversations.entity_type` ships); `AGENTS_REQUEST_CHAT` stub durable consumer logs + re-publishes transient `AGENTS_RUN_EVENT`; `AGENTS_RUN_EVENT` fanout pushes `agents.run.event` to participants/workspace members via `connection_manager.push_many`. Tests `tests/test_invocation_framework.py`: 4 (subjects, SessionStore roundtrip/delete, LocalTmpRunner provision/execute/close, router publishes per active agent skips inactive). | ChatHandler + real runner execution + `conversations.entity_type` + `agent_session_ref` remain TODO (Phases 5–6). |
| **5** | Chat Handler + Inbox | ⬜ **TODO** | — | `ChatHandler`, permission pause/resume (`agent_permission_requests`), `agent_session_ref`, `AgentAvatar` in thread/compose, collapsed enrichment + "View session log". |
| **6** | Runner Backends | ⬜ **TODO** | — | `LocalTmpRunner` + `VercelSandboxRunner` behind `RunnerService`; `agent:{id}:*` env injection only here. |
| **7** | Memory | ⬜ **TODO** | — | `agent_memories` + pgvector + `MemoryStore` (triple-isolated). |
| **8** | Platform MCP (registry) | ⬜ **TODO** | `role_id` on `agents` already models the gate (null = no platform access); deny-by-default. | `mcp/platform/registry.py` + `tools/*.py` + MCP server + per-call `role ∩ user` scope + audit. |
| **9** | Usage Dashboard | ⬜ **TODO** | `agent:usage:read` permission already seeded. | `agent_usage` table + `GET /agents/usage` + `AgentUsageDashboardPage`. |
| **10** | Scheduled Invocation | ⬜ **TODO** | — | `JobSpec("agents.scheduled_run")` + auto-registered per-agent job + `JobRun` observability. |
| **11** | Extension Guide + Hardening | ⬜ **TODO** | — | Docs-only "Add a tasks entity" + hardening notes. |

Deferred-work entries added for Phases 3–11 (see `_bmad-output/implementation-artifacts/deferred-work.md`).

---

## 1. Current State (verified — updated 2026-08-31)

- **Inbox messaging: implemented.** `apps/api/src/models/conversation.py` (`conversations`, `conversation_participants` — polymorphic `participant_type=user|agent` with dual `user_id`/`agent_id` columns, `messages` with `sender_type`), `apps/api/src/services/conversations.py` (`ConversationService`: create/send/list/rename/read/archive/unread), `apps/api/src/api/routes/conversations.py`, frontend `components/inbox/*` + `ComposeDialog` + Tiptap + `liveProvider` `message.created`.
- **User profiles: implemented.** `apps/api/src/models/user_profile.py` (pattern to mirror: `custom_data JSON`), `apps/web/src/lib/avatar.ts` (centralized avatar helpers — extend, don't duplicate).
- **Agents foundation: implemented.** Alembic head = `0008_workspace_settings` (was `0007_agents`; `0008` this round). `models/agent.py`, `services/agents.py` (+ `workspace_settings.py`), `api/routes/{agents,workspace_settings}.py`, `events/subjects.py` (`agents.profile.changed` transient + `agents.requests.chat` durable + `agents.run/permission.event` transient), `workflows/__init__.py` (agent profile fanout + message→`agents.requests.chat` routing + stub `agents.run.event` fanout), `events/nats.py` (`agents.>`), `agents/{handlers, runners, sessions, registry}` framework stubs + `LocalTmpRunner` + `SessionStore`, `api/tests/{test_agents,test_workspace_settings,test_invocation_framework}.py`, web: `types.ts` (`Agent`, `AgentSecretInfo`), `permissions.ts` + `accessControlProvider.ts` (`agents`), `lib/avatar.ts` (`parseAvatarValue`) + `components/ui/agent-avatar.tsx`, `settings.py` (`agent_llm_providers` + `agent_default_model` + `agent_runner_*` + `agent_mcp/vector/cost/permission_ttl`), `App.tsx` (`agents` resource + workspace settings `agents-general/agents-sandbox` routes), `AppLayout.tsx` (Agents nav), `pages/agents/{Agents,AgentCreate,AgentEdit}Page.tsx`, `pages/settings/workspace/{registry,sections/*}` (Agents/Sandbox via `GenericSettingsLayout` pattern). Secrets via `SecretStore` (`agent:{agent_id}:{KEY}` + `workspace:{id}:setting:{key}`) encrypted, masked `{has_value}` on read. RBAC: `agent:*` seeded; `workspace:update` gates settings writes; `agent:invoke`/`agent:usage:read` still deferred to Phase 5/9. Inbox agent-participant integration still deferred to Phase 5.

**Key files to touch (remaining):** `models/{agent_memories,agent_usage,agent_permission_requests,__init__}.py`, `services/{agents(Ch.5+),memory}.py`, `api/routes/{agents(Ch.5+,usage)}.py`, `workflows/__init__.py` (remaining routing — entity_type dispatch), `realtime/manager.py`, `jobs/builtin.py`; web: `types.ts` (remaining types), `App.tsx` (remaining resources), `providers/{liveProvider}.ts`, `components/inbox/*`, `pages/{AgentUsage*}.tsx`.

---

## 2. Architecture — The Invocation Pipeline

```
                     ┌──────────────────────────────────────────────────────────────┐
                     │                    HANDLER REGISTRY                          │
                     │   entity_type → AgentHandler (chat, task, …)                 │
                     └──────────────────────────────────────────────────────────────┘
request (entity event)                                                             
  e.g. conversations.message.created ──► router workflow:                          
     • find agent participants (participant_type=agent, is_active)                 
     • entity_type = conversation.entity_type                                      
     • publish durable "agents.requests.{entity_type}"  ◄── dedicated queue/handler
                                        │                                          
                                        ▼                                          
                              AgentHandler.on_request (wake/claim, dedupe by       
                              conversation+message+agent; or RESUME after decision)
                                        │                                          
                    1. collect_context():  history, workspace-scoped memory            
                       (workspace,agent,user), platform tools, MCP, session ref        
                    2. execute via RunnerService (isolated runtime):                   
                         provision → execute → stream events back → close             
                         [LocalTmp+gVisor | Vercel Sandbox | Docker/E2B later]        
                         ↳ tool gate hits requires_permission? → PERMISSION FLOW      
                    3. post-process ("update handler"): persist final reply,          
                       agent_session_ref, agent_usage, audit,                          
                       notifications (handler picks recipients + deep-link),           
                       ConnectionManager.push to watching users                        
```

**Design rules**
- **Handlers** own: session/conversation storage semantics, retrieval, **context construction**, chat history, tools + **approval policy**, **whether platform MCP is injected** (per-handler decision), **session-history retrieval/enrichment**, notification policy, deep links. Same base interface for all entities.
- **Runners** are reusable execution services (provision → execute → stream back → close). Handlers never know the driver.
- **Requests** are entity events; **queues** are durable per-handler subjects (`agents.requests.chat`, …) — same workqueue semantics as `jobs.execute` (NATS JetStream prod, in-process dev).
- **Platform MCP security:** access = intersection of the **agent's assigned role** permissions and the **triggering user's** permissions, verified inside the platform MCP on every tool call (defense in depth: agent can't exceed its role, nor the invoker's rights). Read-only agents = assign a read-only role.
- Messaging tables store **final messages only**. Harness-internal history (tool calls, thinking) lives in handler-managed session storage and is fetched **lazily for enrichment** (chat) or on demand (session-log dialog for other entities).

---

## 3. Build Order (Phases)

### Phase 0 — Permissions & Types — ✅ Shipped (2026-08-30)

- `apps/api/src/core/permissions.py`: `agent:read`, `agent:manage`, `agent:invoke` (session users pass, API-key gated via `require_key_permission` like `message:send`), `agent:usage:read`. Seed owner/admin all; editor/viewer read+invoke. Permission-request decisions: the **triggering user** decides; approving a mutating platform tool additionally requires the corresponding platform permission (e.g. approving `member.invite` needs `member:invite`).
- Mirror in `apps/web/src/permissions.ts` + `PERMISSION_MAP`.
- `apps/web/src/types.ts`: `Agent`, `AgentUsageEntry`, `AgentPermissionRequest`, `SessionStep` types — shipped `Agent` + `AgentSecretInfo`; `AgentUsageEntry`/`AgentPermissionRequest`/`SessionStep` remain TODO (Phases 5/9).

### Phase 1 — DB: `0007_agents` — ✅ Shipped (2026-08-30)

Single **`agents`** table (condensed agent-user + profile; workspace-scoped), modeled after `user_profile.py`:

| Column | Type | Notes |
|---|---|---|
| `id` | `StringUUID` PK | referenced by `conversation_participants.agent_id` |
| `workspace_id` | `StringUUID` idx NOT NULL | tenant scope |
| `slug` | `String(100)` UQ per workspace | job keys, URLs |
| `name` | `String(150)` | display name (agent identity) |
| `description` | `Text` nullable | |
| `avatar` | `String(300)` nullable | **flexible**: `url:https://…` \| `emoji:🤖` (unprefixed heuristic: http→url else emoji). Parsers later. |
| `system_prompt` | `Text` | |
| `model` | `String(100)` **nullable** | null → resolved at run: workspace setting `agents.default_model` → `settings.agent_default_model` |
| `temperature`, `max_tokens` | `Float`/`Int` nullable | |
| `tool_allowlist` | `JSON` list[str] nullable | |
| `mcp_servers` | `JSON` list[{id, url, transport, auth_secret_ref?, enabled, timeout_ms}] | manual per-agent; platform MCP not stored here |
| `execution_target` | `String(30)` nullable | `local` \| `vercel` (defaults from workspace settings) |
| `role_id` | `StringUUID` nullable, idx | **agent's workspace role** (`roles` table) — scopes what the platform MCP may do for this agent (assign a read-only role for read-only agents; null = platform MCP unavailable) |
| `skills` | `JSON` list[str] default [] | **skill ids** (stable across renames; the deferred skills directory will own id→slug resolution) |
| `is_active` | `Bool` default true | |
| `custom_data` | `JSON` default dict | user-profile pattern for dev extensions |
| `created_by_user_id` / `updated_by_user_id` | `StringUUID` idx | |
| timestamps | `TimestampMixin` | |

**Skills directory deferred** — the column exists now (ids only); the registry/directory that gives skills meaning comes later.

**Agent secrets / env vars (not a JSON column):** agent-specific env (e.g. `ANTHROPIC_API_KEY`, per-agent values) stored in the existing `SecretStore` (`stored_secrets`) under logical keys **`agent:{agent_id}:{ENV_VAR_NAME}`** — encrypted at rest (Fernet), workspace-scoped, rotation/versioning for free, and isolated per agent id (AgentService validates + exposes `list_for_agent`; `stored_secrets.secret_key` already supports 400-char logical ids like `integrations:<id>:client_secret:<key_id>`). Managed per-agent in the UI (write-only, masked after save); resolved at run time and injected **only into that agent's runner** as env vars. A plaintext JSON column on `agents` is rejected deliberately — it would be readable in any admin query/backup with no encryption or audit trail.

Extend messaging + add pipeline tables — shipped `agents` only; the following remain TODO (Phases 4–5/7):
- `conversations.entity_type` `String(30)` NOT NULL default `"chat"`, indexed — authoritative handler-routing key; future entities reuse `conversation_id` as entity id. Messages inherit via join (no denormalized column on `messages`).
- `conversation_participants.agent_session_ref` `String(500)` nullable — per-agent-participant opaque session id (each participant has its own session; the conversation row can't hold it). Handler loads to resume, writes back after run/pause.
- **`agent_permission_requests`** (approval gates): `id, workspace_id idx, conversation_id idx, agent_id idx, user_id (decider = triggering user), run_message_id nullable, tool_name, args_summary JSON, status (pending|approved|denied|expired|cancelled), decision_note nullable, decided_by_user_id nullable, created_at, decided_at, expires_at`. Max one pending per `(conversation_id, agent_id)`.
- Schemas: `AgentCreate/Update` (avatar prefix, model allowlist when set, mcp shape), `MCPServerSpec`, `PermissionDecision`, `AgentUsageQuery` in `schemas/agents.py` — shipped `MCPServerSpec` + `AgentCreate/Update`; `PermissionDecision`/`AgentUsageQuery` still TODO.
- Settings: `agent_llm_providers`, `agent_default_model`, `agent_runner_driver (local|vercel)`, `agent_runner_root` (tmp base, e.g. `/tmp/agent-runs`), `agent_mcp_enabled`, `vector_enabled`, `agent_cost_table`, `agent_permission_ttl` — shipped first two; rest TODO.

### Phase 2 — Agents CRUD + Admin UI — ✅ Shipped (2026-08-30)

- `services/agents.py` (session+bus+cipher pattern): CRUD; validate model allowlist/mcp/avatar; secrets via `SecretStore`; publish `agents.profile.changed`; audit.
- `api/routes/agents.py`: `/agents` CRUD with `apply_query` + `X-Total-Count`, `require_key_permission("agent:manage"|"agent:read")` + `get_current_workspace_id` — shipped with `require_permission(AGENT_READ/AGENT_MANAGE)` (session + API-key enforcement via unified `require_permission`; `agent:invoke`/`agent:usage:read` unused here by spec).
- Web: `agents` resource in `App.tsx` (`/agents`, `/agents/create`, `/agents/:id`); `AgentsPage` (`ListView`), `AgentCreatePage`/`AgentEditPage` (`CreateView`+`useForm`+`zodResolver`) — fields: avatar input with live preview, MCP repeater, tool allowlist, execution target, model (optional — "use workspace default" when empty), **role select** (workspace roles; "none" = no platform MCP access), **skills** (deferred — show disabled placeholder until the skills directory exists), **Secrets & Env editor** (key + value rows; value write-only, masked after save; routed through `AgentService` → SecretStore `agent:{agent_id}:{KEY}`; delete supported; `agent:manage` gated). `execution_target` is now a `Select` (`local`/`vercel`/no-preference); `max_tokens` defaults to `200000`; create now `redirect: "list"`; MCP repeater uses `FormField` (prior orphaned `FormLabel` crash fixed).
- **Avatar parsing:** extend `apps/web/src/lib/avatar.ts` with `parseAvatarValue(value) -> {kind:"url"|"emoji", value}` + fallback initials; `AgentAvatar` component used by compose/thread/list views.

### Phase 3 — Workspace Settings Page (extensible registry) — ✅ Shipped (2026-08-31)

- **Backend:** `workspace_settings` table (`0008_workspace_settings`): `id, workspace_id idx, key String(100), value JSON, updated_by_user_id, timestamps`, UQ `(workspace_id, key)`. `services/workspace_settings.py` (validated keys per section; sensitive values stored as `secret_ref` → `SecretStore` encryption, never plaintext). Routes: `GET /workspace-settings`, `GET /workspace-settings/{key}`, `PUT /workspace-settings/{key}` (`workspace:update`; read via `workspace:read`), `DELETE /workspace-settings/{key}`; `PUT null` clears (delete), audit `workspace_setting.updated/deleted`; masking `has_value`.
- **Frontend registry:** `apps/web/src/pages/settings/workspace/registry.ts` — `createSettingsRegistry` + `workspaceSettings` (`agents-general`/`agents-sandbox` tabs, `workspace:read`, order 60/61); `App.tsx` wires `/settings/workspace/agents-general|sandbox`. v1 sections: `AgentsGeneralSection` (default model/runner/memory TTL, `Checkbox` + `Select` sentinel) + `AgentsSandboxSection` (vercel team_id/token write-only + `has_value` + Delete, timeout).

### Phase 4 — Invocation Framework Core — ✅ Shipped (2026-08-31)

- **Subjects** (`events/subjects.py`): `AGENTS_REQUEST_PREFIX = "agents.requests."` (durable), `AGENTS_REQUEST_CHAT = "agents.requests.chat"` (durable workqueue), `AGENTS_RUN_EVENT`/`AGENTS_PERMISSION_EVENT` (transient, `→` fanout). `STREAM_SUBJECTS` extended `agents.>`.
- **Handler framework** `apps/api/src/agents/handlers/base.py`: `AgentRequest`/`AgentContext`/`AgentEvent` + `AgentHandler` Protocol (`entity_type/queue_subject/inject_platform_mcp`, `on_request/collect_context/execute/retrieve_session_history/post_process/pause_for_permission/resume`); `agents/registry.py` wiring dict.
- **Runner interface** `apps/api/src/agents/runners/base.py`: `RunSpec`/`RunHandle` + `RunnerService` Protocol (`provision/execute/close`); `LocalTmpRunner` (tmpdir under `agent_runner_root`, stub `done`, `close` rm).
- **Session storage:** `agents/sessions/store.py` `SessionStore` — JSON `root/ws/agent/conv/session.json`, `write/read/delete`.
- **Router workflow** (`workflows/__init__.py`): wraps durable `conversations.message.created` to also publish `AGENTS_REQUEST_CHAT` per active `agent` participant (skips inactive, entity_type="chat" hardcoded until `conversations.entity_type` ships); `AGENTS_REQUEST_CHAT` stub durable consumer + `AGENTS_RUN_EVENT` fanout via `connection_manager.push_many`.

### Phase 5 — Chat Handler + Inbox Integration (first pipeline, end-to-end) — ⬜ TODO

- `ChatHandler`:
  - `collect_context`: profile, conversation history (`messages`), memory slice `(workspace_id, agent_id, user_id)` (Phase 7), `agent_session_ref`, platform tools (if `inject_platform_mcp`) + manual MCP (allowlist-filtered), agent role + user permissions (effective scope for platform MCP), agent env secrets (from SecretStore `agent:{agent_id}:*`), model = `profile.model ?? workspace setting ?? settings.agent_default_model`.
  - `execute`: Pydantic AI agent inside runner; stream `thinking|token|tool_call|tool_result|error`.
  - `post_process`: persist **final assistant reply only** (`messages`, `sender_type="agent"`), update `agent_session_ref` + session store, `agent_usage`, audit, notification pointers with handler deep-link (`/inbox?tab=messages&conversationId=…`), WS push.
  - `retrieve_session_history`: reads session store → `{steps: [{message_id, kind: thinking|tool_call|tool_result, title, content, duration_ms, status}]}`.
- **Permission flow (approval gates):**
  1. Tool flagged `requires_permission` (default: shell/code-exec + mutating platform tools) → harness calls gate before execution.
  2. Handler pauses: insert `agent_permission_requests` (pending), persist session + `agent_session_ref`, close runner (**agent idles — resources released**), emit transient `agents.permission.event`.
  3. UI (`ThreadView`): pending-permission banner rendered from the event or conversation/session fetch (NOT a message row) — Approve / Deny + args summary.
  4. `POST /agents/permission-requests/{id}/decision` `{approved, note?}` → handler validates decider (triggering user; platform permission for tool-level approval) → publishes resume `agents.requests.chat` with decision → handler re-provisions runner, resumes session via `agent_session_ref`, injects tool result or denial, loop continues.
  5. TTL: pending requests expire (`agent_permission_ttl`) → status `expired`, run ends failed.
- **Inbox integration:** `create_conversation` accepts agent participants (active, same workspace); `ComposeDialog` lists `useList<Agent>` with bot badge; `ThreadView` renders agent bubbles via `AgentAvatar`.
- **Session enrichment (chat-specific UX):** messages fetch as today (fast path); after load, `ThreadView` async-fetches `GET /conversations/{id}/session-history` (handler-routed) and renders **collapsed-by-default** step groups (thinking/tool calls) between assistant bubbles, expandable. Other entities (future) instead render a "View session log" button → dialog with the full log — same handler function, different presentation.
- Frontend streaming: Vercel AI SDK `useChat` (see §4) with polling fallback.

### Phase 6 — Runner Backends (v1: local + Vercel Sandbox) — ⬜ TODO

All behind `RunnerService`; handlers never know the driver. Docker/E2B/Daytona adapters deferred (interface already supports them).
- **LocalTmpRunner (dev/default):** dedicated tmp dir under `agent_runner_root` (never the repo), subprocess with resource caps, `runsc` (gVisor) when available, network off by default, clean FS per run. Receives agent env secrets (`agent:{agent_id}:*`) as env vars — only that agent's values.
- **VercelSandboxRunner:** Vercel Sandbox adapter — ephemeral sandboxes, snapshot/restore, FS + exec APIs; credentials from workspace settings (Phase 3); same provision/execute/close contract; session artifacts fetched back into `SessionStore`.
- **gVisor rationale:** broad compatibility (Docker drop-in runtime), userspace syscall filtering, lighter than Firecracker; dev fallback = plain process + tmp dir (documented degraded isolation).
- Credential isolation: `DATABASE_URL`/`FERNET_KEYS` never enter a run; secrets resolved host-side, injected per-tool.

### Phase 7 — Memory (workspace+agent+user) — ⬜ TODO

- `0009_agent_memories`: `id, workspace_id, agent_profile_id, user_id, conversation_id nullable, kind(fact|preference|summary), content Text, embedding vector(1536) nullable (pgvector)`, composite idx `(workspace_id, agent_profile_id, user_id)`.
- `collect_context` retrieves top-k (embedding + recency) for the triple; `post_process` LLM-extracts facts/preferences and upserts. TTL/prune per triple.
- Isolation test: user A cannot retrieve user B's memories for same agent+workspace.
- Start Postgres+pgvector; `mem0` behind `MemoryStore` interface if extraction quality needs it.

### Phase 8 — Platform MCP (extensible registry, role-gated) — ⬜ TODO

- **Injection is handler-controlled:** the handler decides whether to attach platform MCP to a run (`inject_platform_mcp`); nothing auto-injects. External MCP servers remain **manually added per agent**, allowlist-filtered, no curated defaults.
- **Extensible tool registry** `apps/api/src/mcp/platform/`:
  ```
  platform/
    registry.py        # @platform_tool(name, permission, mutates: bool) decorators; auto-discovery
    tools/             # one module per entity — developers add tools here
      workspaces.py    #   workspace.read, workspace.update …
      members.py       #   member.list, member.invite …
      conversations.py #   conversation.rename, conversation.list …
      <entity>.py      #   new entity/model → new module, tools auto-register
    server.py          # streamable-http MCP server over the registry (internal network)
  ```
  Adding platform capability = drop a decorated tool function in a tools module (proxying existing service methods for behaviour parity) — registry picks it up; no framework changes.
- **Security verification (per call, inside the MCP server):**
  1. Identify the agent (`agent_id` from run context) → load `agents.role_id` → role permissions. `role_id` null → **deny all** platform tools.
  2. Effective scope = `agent_role_permissions ∩ triggering_user_permissions` (agent never exceeds its role, nor the invoker's rights).
  3. Tool's declared `permission` must be in effective scope; `mutates: true` tools additionally flow through the **approval gate** (Phase 5 permission requests).
  4. Every platform tool call → `audit_log_entries`.
  Read-only agents = assign a viewer-like role; deny-by-default keeps new tools safe until a role grants them.
- Timeouts + circuit breakers for external MCP; platform MCP is local (low latency).

### Phase 9 — Cost & Usage Monitoring Dashboard — ⬜ TODO

- `0010_agent_usage`: `id, workspace_id, agent_id, user_id, conversation_id, message_id, model, input_tokens, output_tokens, total_tokens, cost_cents Numeric(10,4), latency_ms, tool_calls_count, status, created_at` (+idx workspace/agent/date).
- `GET /agents/usage` + `GET /agents/{id}/usage` (`agent:usage:read`, filterable `{agent_id, user_id, model, status, from, to}`, `X-Total-Count`, CSV option).
- Web `AgentUsageDashboardPage` (`/agents/usage`): filters, KPIs, charts (recharts), recent-runs linking to conversations; gated via `useCan`.

### Phase 10 — Scheduled Invocation — ⬜ TODO

- `JobSpec(key="agents.scheduled_run", scope="workspace", params={agent_id, prompt, conversation_id?})` → builds/loads a conversation → publishes `agents.requests.chat` with configured service user. Optional per-agent `agents.cron_schedule` + auto-registered `JobSpec(key=f"agents.profile.{slug}")` via `sync_definitions`. Observability via existing `JobRun`/`JobLogEntry` UI.

### Phase 11 — Extension Guide + Hardening (documented, not coded) — ⬜ TODO

- **"Add a tasks entity" walkthrough (docs only):** task row creates/uses a conversation with `entity_type="task"`; `TaskHandler` implements the same interface (comments = `messages`; handler picks notification recipients + deep link to task page; enrichment optional → "View session log" dialog instead of inline steps); register `agents.requests.task` queue; frontend: task page + notification deep-link branch. No platform code changes beyond handler registration.
- Observability: Logfire/OpenTelemetry per run; run logs NOT in messaging tables.
- Hardening: budget caps per triple; approval gates (Phase 5) as the human-in-the-loop layer; allowlist + sandbox + no shell by default.

---

## 4. Harness — Pydantic AI + Vercel AI SDK (complementary)

**Yes — they operate on different layers and compose cleanly:**
- **Pydantic AI (server, Python):** the agent loop — tools, MCP, memory, sessions, Logfire. Runs inside the runner; emits typed events.
- **Vercel AI SDK (client, TS):** rendering/streaming layer — `useChat` consumes a stream; natively renders tool calls and reasoning ("thinking") parts.
- **Bridge:** the chat handler's SSE endpoint translates `AgentEvent`s into the AI SDK **data-stream protocol** (small serializer: token → text-delta, tool_call/tool_result → tool parts, thinking → reasoning part, permission-request → custom data part). No vendor coupling: polling/WS fallback works without the protocol.

**Primary harness: Pydantic AI** (MIT, native MCP, model-agnostic, stack fit). LangGraph remains a swap-in behind the handler interface. Alternatives evaluated (Jul 2026): OpenAI Agents SDK, Agno, CrewAI, MS Agent Framework, ADK, Strands, LlamaIndex, Mastra — see sources.

## 5. Research Sources

- Harnesses: [All Agent Harnesses: The Live Comparison](https://htek.dev/articles/all-agent-harnesses-live-comparison) · [AI Agent Frameworks Compared](https://changegamer.ai/resources/agent-frameworks-compared)
- Sandboxes: [E2B vs Daytona vs Modal vs Cloudflare vs Vercel Sandbox](https://www.developersdigest.tech/blog/ai-agent-code-sandbox-comparison-2026) · [Vercel Sandbox docs](https://vercel.com/docs/vercel-sandbox)
- Memory: [Agent Memory Systems Compared (mem0/Zep/Letta/Cognee)](https://fountaincity.tech/resources/blog/agent-memory-knowledge-systems-compared/)
- MCP + AI SDK: [vercel.com/docs/connect/frameworks/ai-sdk-and-mcp](https://vercel.com/docs/connect/frameworks/ai-sdk-and-mcp)
- In-repo: `plans/inbox-messaging-plan.md` (messaging design, now implemented)

---

## 6. Risks & Mitigations

- **Hot files:** `models/__init__.py`, `settings.py`, `types.ts` — keep agent code in new modules; check `.codesight/graph.md`.
- **Session-ref concurrency:** dedupe `(conversation_id, message_id, agent_id)` + per-conversation agent lock; a paused (permission-pending) agent claims the conversation so new messages queue behind the decision.
- **Secret isolation:** SecretStore keys namespaced `agent:{agent_id}:{KEY}`; every read resolves agent id from the run context (never from client input); add isolation test (agent A cannot read agent B's secrets; cross-workspace denied).
- **Platform MCP over-grant:** deny-by-default (`role_id` null = no access); effective scope = agent role ∩ user permissions, re-verified per call; mutating tools behind the approval gate; all calls audited.
- **Session store durability:** local disk is ephemeral — dev-only acceptable; Vercel runner stores artifacts with the sandbox/snapshot; document retention + optional object-store backend later.
- **pgvector on SQLite/embedded dev:** vector features behind `vector_enabled`; recency-only fallback in dev.
- **Multi-replica streaming:** transient fanout subject → every replica pushes to its WS clients (pattern matches `notifications.created`).
- **Runner sprawl:** `RunnerService` is the only execution boundary; never raw `subprocess` outside it.

## 7. Verification

- Backend: `alembic upgrade head`; pytest: agent CRUD scoping (404 cross-workspace), permission matrix, router workflow (message → `agents.requests.chat` → assistant row), **pause/resume permission flow** (gate → pending request → decision → session resumes; expired request fails run), session-ref resume across turns, memory triple-isolation, usage rows per run, workspace-settings validation + secret storage, **agent secret isolation** (`agent:{id}:*` namespacing; cross-agent/cross-workspace denied), **platform MCP scope** (read-only agent denied mutations; scope = agent role ∩ user permissions; `role_id` null → denied).
- Frontend: `npm run build`; manual QA — create agent → compose with agent → stream tokens/tool calls → **collapsed thinking/tool steps expand** → reply persists → session resumes → **permission banner appears for gated tool → approve resumes run** → usage dashboard reflects run → workspace settings persist sandbox credentials + defaults; avatar emoji/url render.
- Runner: sandbox test asserts tmp-dir isolation, network off, time cap, no `FERNET_KEYS` visible; gVisor smoke when `runsc` present; Vercel sandbox smoke against real credentials (staging).
- Jobs: scheduled run produces `JobRun` + agent reply within one scheduler tick.

