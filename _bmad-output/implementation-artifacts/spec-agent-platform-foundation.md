---
title: 'Agent Platform — Foundation (agents CRUD, permissions, secrets)'
type: 'feature'
created: '2026-08-30'
status: 'in-progress'
review_loop_iteration: 0
baseline_commit: '98779ee0eb1b0569873caa85e0b488134f824731'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The platform has no first-class agent entity — workspaces cannot define, configure, or administer AI agents (identity, model, tools, MCP servers, execution target, workspace role, per-agent secrets). This foundation is prerequisite to every later agent-platform phase (invocation pipeline, memory, MCP, usage).

**Approach:** Mirror the codebase's existing workspace-scoped CRUD patterns (user_profile model shape, service + route conventions, refine ListView/CreateView pages) to add an `agents` table + migration `0007`, `AgentService` with SecretStore-backed per-agent env vars, `/agents` REST routes with new `agent:*` permissions, and admin UI (list/create/edit) with flexible `url:`/`emoji:` avatar rendering.

## Boundaries & Constraints

**Always:**
- Follow existing patterns: service error hierarchy + workspace scoping (fetch → verify `workspace_id` → 404) + `publish_event`/`publish_audit` after commit; routes with `parse_query`/`apply_query` + `X-Total-Count`; frontend ListView/CreateView + `useForm` + `zodResolver`; reuse `lib/avatar.ts` helpers.
- Secrets only via `SecretStore` under logical key `agent:{agent_id}:{ENV_VAR_NAME}`; workspace_id resolved from the agent row, never client input. Secret values never appear in the `agents` table, list/detail responses, audit payloads, events, or logs.
- `role_id`, when set, must reference a role in the same workspace (else 422).
- Declare `agent:invoke` and `agent:usage:read` now (seeded per plan) but leave them unused by endpoints — later phases consume them.

**Ask First:**
- If refine v5's `useForm action:"edit"` cannot seed the edit form cleanly and a deviation from refine conventions is needed, propose it before implementing.
- If any secret read-back API (returning values) seems needed, propose the shape first — default is strictly write-only.

**Never:**
- No invocation/runtime/LLM code, chat handler, runners, workspace-settings page, platform MCP, memory, or usage endpoints — all deferred.
- No conversation/ComposeDialog/inbox changes (agent participants in inbox come with the pipeline phase).
- No plaintext secret storage anywhere; no secret values in any response or log.
- Do not add later-phase tables (`agent_permission_requests`, `workspace_settings`, memories, usage) to the 0007 migration; do not touch `conversations`/`conversation_participants` schema.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Cross-workspace access | GET/PATCH/DELETE `/agents/{id}` where agent's workspace ≠ header workspace | — | 404 (indistinguishable from missing) |
| Slug conflict | POST/PATCH with `slug` already used in same workspace | — | 409; same slug in a different workspace → 201 |
| Secret key validation | PUT `/agents/{id}/secrets/{key}` with `key` not matching `^[A-Z_][A-Z0-9_]*$` or making the logical key exceed 400 chars | — | 422 |
| Secret listing | GET `/agents/{id}/secrets` | `{key, created_at}` entries only — no values | — |
| Foreign role | POST/PATCH with `role_id` from another workspace | — | 422 |
| Model allowlist | `model` not in `settings.agent_llm_providers` when that setting is non-empty | — | 422 |
| Missing permission | editor calls POST `/agents` (editor holds read+invoke only) | — | 403 `missing permission: agent:manage` |

</frozen-after-approval>

## Code Map

- `apps/api/src/models/user_profile.py` -- model-shape exemplar (`Mapped[...]` + `mapped_column`, `custom_data` JSON `default=dict`)
- `apps/api/src/db/base.py` -- `StringUUID` (L12–35), `Base` naming_convention, `TimestampMixin` (L50–56)
- `apps/api/src/models/agent.py` -- NEW `Agent(Base, TimestampMixin)`: id StringUUID PK uuid4 default; workspace_id StringUUID idx NOT NULL; slug String(100); name String(150); description Text; avatar String(300); system_prompt Text; model String(100) nullable; temperature Float nullable; max_tokens Int nullable; tool_allowlist JSON nullable; mcp_servers JSON default list; execution_target String(30) nullable; role_id StringUUID nullable idx; skills JSON default list; is_active Bool default true; custom_data JSON default dict; created_by_user_id/updated_by_user_id StringUUID nullable idx
- `apps/api/src/models/__init__.py` -- import + `__all__` registration (user_profile L18 pattern) — required for `Base.metadata`/alembic env
- `apps/api/src/models/conversation.py` -- `ConversationParticipant.agent_id` (L42) and `Message.sender_agent_id` (L63) are StringUUID strings — agent ids must stay string-form; do not modify this file
- `apps/api/src/models/workspace.py` -- `Role` (L52–64): id/workspace_id/name/permissions JSON/system — target of role_id
- `apps/api/src/services/workspaces.py` -- service exemplar: ctor `(session, bus)` (L35–38), scoping checks (L274/329), commit-then-publish, `publish_audit` (L90–99); `sync_system_role_permissions` (L589–610) auto-propagates role-seed changes at startup
- `apps/api/src/services/agents.py` -- NEW `AgentService(session, bus)`: `AgentError`/`AgentNotFound`/`AgentConflict` hierarchy; CRUD with slug rules (absent → slugify name `^[a-z0-9-]+$`, uniqueness per workspace → 409), avatar ≤300 chars, validation per I/O matrix; secrets via `container.secret_store`: `list_secret_keys` (strip values → `{key, created_at}`), `set_secret`, `delete_secret`; `publish_event(Subjects.AGENT_PROFILE_CHANGED, ..., transient=True)` + `publish_audit("agent.created|updated|deleted"|"agent.secret.set|deleted")`
- `apps/api/src/secrets/base.py` -- `SecretStore` ABC: `put/get/delete/list_for_workspace(workspace_id, prefix)` (L38–66); `list_for_workspace` returns full decrypted records → service MUST strip values
- `apps/api/src/secrets/db_store.py` -- `DbSecretStore(session_factory, cipher)`; `secret_key` String(400) unique per workspace; prefix LIKE
- `apps/api/src/container.py` -- `Container.secret_store` (L31), `.bus`, `.cipher` — routes get via `Depends(get_container)`
- `apps/api/src/core/permissions.py` -- constants (L17–18), `ALL_PERMISSIONS` (L31–49), `permissions_for_role` (L52–86): add `AGENT_READ/AGENT_MANAGE/AGENT_INVOKE/AGENT_USAGE_READ`; owner+admin → all four; editor+viewer → read+invoke
- `apps/api/src/api/deps.py` -- `require_permission` (L155–187), `require_key_permission` (L111–141, unused here), `get_current_workspace_id`, `get_db`
- `apps/api/src/api/crud.py` -- `parse_query` (L66), `apply_query` (L139–161), `run_list` (L164–179); `InvalidQuery` → 422
- `apps/api/src/api/routes/roles.py` -- route exemplar: `_role_dict` serializer (L30–39), list + `X-Total-Count` (L42–61), 404 on workspace mismatch (L97–99), `request.client.host` for audit ip (L85), filterable/sortable module constants (L26–27)
- `apps/api/src/api/routes/api_keys.py` -- delete → 204 + error→404/409 mapping (L119–139)
- `apps/api/src/api/routes/agents.py` -- NEW `APIRouter(prefix="/agents", tags=["agents"])`: GET list (`agent:read`), POST (201), GET/PATCH/DELETE `/agents/{id}` (`agent:read`/`agent:manage`), GET/PUT/DELETE `/agents/{id}/secrets[/{key}]` (`agent:manage`; PUT body `{value}` upserts); serializer `_agent_dict` (isoformat datetimes; never includes secrets); `require_permission` deps
- `apps/api/src/schemas/api.py` -- add `AgentCreate`/`AgentUpdate` (Update `ConfigDict(extra="forbid")`, ProfileUpdate L124–125 pattern) + `MCPServerSpec {id, url, transport: "http"|"sse", auth_secret_ref?, enabled, timeout_ms?}`; Field min/max mirroring columns; temperature 0–2, max_tokens > 0
- `apps/api/src/settings.py` -- add section: `agent_llm_providers: str = ""` (comma-separated allowlist; empty = any model), `agent_default_model: str = ""`
- `apps/api/src/events/subjects.py` -- add `AGENT_PROFILE_CHANGED = "agents.profile.changed"` to `Subjects`, `TRANSIENT_SUBJECTS` (L54–58), `ALL` (L61–77)
- `apps/api/src/workflows/__init__.py` -- `build_workflows` (L60–65); register fanout handler mirroring L389/L330 pattern: on `agents.profile.changed` → `connection_manager.push_many` to workspace member user ids
- `apps/api/src/main.py` -- `app.include_router(agents.router, prefix=API)` (router block L102–115)
- `apps/api/alembic/versions/0006_user_profiles.py` -- migration shape: revision chain, dialect-aware ID (L33–34), `has_table` guard (L27–31), `_ts`/`_id` helpers; JSON `server_default=sa.text("'{}'")` / `"'[]'"` for defaults
- `apps/api/alembic/versions/0007_agents.py` -- NEW: `revision="0007"`, `down_revision="0006"`; create `agents` table per model; unique `(workspace_id, slug)` named `uq_agents_workspace_slug`; indexes on workspace_id, role_id, created_by_user_id, updated_by_user_id; downgrade drops table
- `apps/api/tests/conftest.py` -- `app_client`, `register_user`, `login`, `ws_headers` (L110–113) helpers
- `apps/api/tests/test_api_keys.py` -- CRUD + permission-matrix test exemplar (L11–18, L56–100)
- `apps/api/tests/test_agents.py` -- NEW: coverage per AC + I/O matrix
- `apps/web/src/types.ts` -- add `Agent` + `AgentSecretInfo {key, created_at?}` near `ApiKey` (L205–216); conventions: snake_case, ISO strings, nullable as `T | null`
- `apps/web/src/permissions.ts` + `apps/web/src/providers/accessControlProvider.ts` -- mirror 4 agent strings in `ALL_PERMISSIONS`; `PERMISSION_MAP` (L8–60): `agents: { list/show: "agent:read", create/edit/delete: "agent:manage" }`
- `apps/web/src/lib/avatar.ts` -- add `parseAvatarValue(value) -> {kind:"url"|"emoji", value}`: explicit `url:`/`emoji:` prefixes; unprefixed heuristic `^https?://` or `data:` → url, else emoji. Extends, does not duplicate, `getAvatarSrc`/`getAvatarData` (L42/51)
- `apps/web/src/components/ui/agent-avatar.tsx` -- NEW `AgentAvatar`: emoji kind → styled text span; url kind → `UserAvatar` (user-avatar.tsx L9–27); fallback initials via `getInitials`
- `apps/web/src/App.tsx` -- resource `{ name: "agents", list: "/agents", create: "/agents/create", edit: "/agents/edit/:id" }` (L52–68 pattern) + routes create-before-list (L82–99); static imports only
- `apps/web/src/components/AppLayout.tsx` -- hardcoded `MENU_ITEMS` (L58–62, permission-gated): add Agents entry gated `agent:read`
- `apps/web/src/pages/agents/AgentsPage.tsx` -- NEW: clone `ApiKeysPage.tsx` (useList L22, ListView/ListViewHeader L28–31, `useCan` row actions L76–84); columns: AgentAvatar+name, slug, model, is_active, role, created_at
- `apps/web/src/pages/agents/AgentCreatePage.tsx` -- NEW: clone `ApiKeyCreatePage.tsx` (useForm + zodResolver + `refineCoreProps: { resource: "agents", action: "create", redirect: false, successNotification }` L63–80); fields: name, slug (auto-fills from name until edited), description, avatar (input + live `AgentAvatar` preview), system_prompt textarea, model optional, temperature, max_tokens, execution_target, role select (useList roles, `__none__` sentinel → null), tool_allowlist (comma input), mcp_servers repeater (array field, add/remove rows), skills (disabled placeholder — directory deferred)
- `apps/web/src/pages/agents/AgentEditPage.tsx` -- NEW (repo's first edit page): refine `useForm` `action: "edit"` + id from route; if refine doesn't auto-populate, `form.reset(record)` in `useEffect` (GeneralSection.tsx L54–92 precedent); same fields as create + is_active toggle + Secrets editor: rows key+value(password), add → PUT, delete → DELETE, values never refetched (JobDetailPage MASK spirit, L49–79)

## Tasks & Acceptance

**Execution:**
- [ ] `apps/api/src/core/permissions.py` -- add 4 agent permission constants to constants + `ALL_PERMISSIONS` + `permissions_for_role` branches (owner/admin all; editor/viewer read+invoke) -- RBAC basis; startup sync propagates to existing workspaces
- [ ] `apps/api/src/models/agent.py` + `apps/api/src/models/__init__.py` -- Agent model + registration -- storage, user_profile pattern
- [ ] `apps/api/alembic/versions/0007_agents.py` -- migration per Code Map -- schema
- [ ] `apps/api/src/settings.py` -- `agent_llm_providers`, `agent_default_model` -- allowlist + future default-model resolution
- [ ] `apps/api/src/schemas/api.py` -- `AgentCreate`/`AgentUpdate`/`MCPServerSpec` with validation -- request contracts
- [ ] `apps/api/src/services/agents.py` -- AgentService (CRUD, validation, secrets, events, audit) -- core logic
- [ ] `apps/api/src/events/subjects.py` + `apps/api/src/workflows/__init__.py` -- subject + fanout WS push -- realtime freshness for future compose/agent lists
- [ ] `apps/api/src/api/routes/agents.py` + `apps/api/src/main.py` -- REST surface + registration
- [ ] `apps/api/tests/test_agents.py` -- tests below -- regression safety
- [ ] `apps/web/src/types.ts` + `apps/web/src/permissions.ts` + `apps/web/src/providers/accessControlProvider.ts` -- types + permission mirror
- [ ] `apps/web/src/lib/avatar.ts` + `apps/web/src/components/ui/agent-avatar.tsx` -- `parseAvatarValue` + `AgentAvatar`
- [ ] `apps/web/src/App.tsx` + `apps/web/src/components/AppLayout.tsx` -- resource, routes, nav item
- [ ] `apps/web/src/pages/agents/` (3 pages) -- list/create/edit UI incl. MCP repeater, role sentinel select, secrets editor

**Acceptance Criteria:**
- Given an owner, when POST `/agents` with a valid body, then 201 returns the agent dict (slug generated when absent, `is_active=true`); an `agent.created` audit entry exists and a workspace member's WS client receives `agents.profile.changed`.
- Given a signed-in member, when GET `/agents`, then 200 with `X-Total-Count` reflecting workspace scoping.
- Given a fresh DB, when `alembic upgrade head`, then the `agents` table exists with unique `(workspace_id, slug)`; downgrade drops it cleanly and re-upgrade is clean.
- Given the UI, when an agent has `url:…`, `emoji:…`, or bare-emoji avatar values, then `AgentAvatar` renders each correctly in list and forms.
- Given the sidebar, when the current user lacks `agent:read`, then the Agents nav item is hidden.
- Given the create form, when name is typed while slug is untouched, then slug auto-fills; server-side conflicts surface as error toasts.

## Design Notes

- Secrets: logical key = `agent:{agent_id}:{ENV_VAR_NAME}`, `ENV_VAR_NAME` validated `^[A-Z_][A-Z0-9_]*$`, total ≤ 400 chars (column limit); `kind="agent_env"`. `list_for_workspace` returns decrypted records — the service maps to `{key, created_at}` before returning. Envelope from routes is write-only: PUT upserts `{value}`, DELETE removes; no read endpoint for values.
- Radix Select forbids empty option values — optional selects (role, execution_target) use an `"__none__"` sentinel mapped to `null` in the submit payload.
- Avatar is a parser-interpreted field: backend only checks length; `parseAvatarValue` owns interpretation (`url:`/`emoji:` prefixes, unprefixed heuristic), so future formats need no schema change.
- `agents.profile.changed` payload: `{workspace_id, agent_id, action: "created"|"updated"|"deleted"}` — transient fanout, no JetStream consumer needed.
- Slug UX: create form auto-slugifies name while the slug field is untouched; server stays authoritative (409 surfaced via toast).

## Verification

**Commands:**
- `cd apps/api && uv run alembic upgrade head` -- expected: 0007 applied; downgrade then re-upgrade clean
- `cd apps/api && uv run pytest tests/test_agents.py -q` then `uv run pytest -q` -- expected: all pass, no regressions
- `cd apps/web && npm run build` -- expected: tsc + vite pass

**Manual checks (if no CLI):**
- Create agent with emoji avatar → renders in list/edit; add env var → masked, listed by key only after save; editor account sees read-only Agents page.
