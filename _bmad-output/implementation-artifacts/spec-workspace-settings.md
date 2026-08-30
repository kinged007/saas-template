---
title: 'Workspace Settings Registry (Phase 3)'
type: 'feature'
created: '2026-08-31'
status: 'in-progress'
baseline_commit: 'agents-foundation'
context: ['plans/agent-platform-plan.md Phase 3']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Agent defaults (default model, runner, sandbox creds, timeouts) and general agent config (memory toggle, permission TTL) are hardcoded or global-only. Workspaces need per-workspace overrides without page surgery for future settings.

**Approach:** Add workspace-scoped `workspace_settings` table + service + REST routes, plus a frontend extensible registry (already exists as `workspace/registry.ts` + `GenericSettingsLayout`) with two new sections (Agents/General, Agents/Sandbox). Sensitive values (Vercel token) go via `SecretStore` encrypted, never plaintext in table/response/log.

## Boundaries & Constraints

**Always:**
- Follow existing patterns: service error hierarchy, workspace scoping (fetch membership → 403 if not member; workspace_id from `X-Workspace-ID` header), `publish_audit` after commit, routes with `X-Total-Count` where list; frontend `useCustomMutation` + `zodResolver`.
- Sensitive `agents.sandbox.vercel_token` stored as `workspace:{workspace_id}:setting:agents.sandbox.vercel_token` kind `workspace_setting` via `SecretStore`; `workspace_settings.value` holds `{"secret_ref": logical_key}` or `{"has_value": true}` masked; never log the value.
- Validate keys against allowlist; unknown key → 422.

**Ask First:**
- If a new sensitive key needs rotation or TTL, propose before extending SENSITIVE_KEYS.

**Never:**
- No invocation/handler/runner code; no agent CRUD changes; no conversation schema changes.
- No plaintext secret in `workspace_settings` table, API response, audit details, or events.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected | Error |
|---|---|---|---|
| List settings | `GET /workspace-settings` member | 200 list of `{key, value, updated_at, updated_by}`; sensitive returns `{has_value: bool}` not raw | 403 if not member; 401 if no auth |
| Upsert | `PUT /workspace-settings/{key}` body `{value}` | 200 persisted; sensitive → SecretStore put + audit `workspace_setting.updated` | 422 unknown key / bad type / enum; 403 missing `workspace:update` |
| Bad enum | `agents.default_runner: "docker"` | — | 422 |
| Sensitive read | GET after PUT token | value is `{has_value:true}` not plaintext | — |
| Cross-workspace | header workspace_id vs stored | 404 indistinguishable | — |
| Delete token | `DELETE /workspace-settings/{key}` sensitive | SecretStore delete + row delete, audit | 404 if missing |

</frozen-after-approval>

## Code Map

- `apps/api/src/models/workspace_setting.py` — NEW `WorkspaceSetting(Base, TimestampMixin)`: id StringUUID PK, workspace_id idx NOT NULL, key String(100) NOT NULL, value JSON NOT NULL server_default `'{}'`, updated_by_user_id nullable idx, UQ (workspace_id, key)
- `apps/api/src/models/__init__.py` — import + __all__
- `apps/api/alembic/versions/0008_workspace_settings.py` — revision 0008, creates table + indexes + UQ
- `apps/api/src/services/workspace_settings.py` — NEW `WorkspaceSettingService(session,bus,secret_store)`: `VALID_KEYS` + `SENSITIVE_KEYS`, `list_settings`, `get`, `upsert`, `delete`; type/enum validation; sensitive → SecretStore `workspace:{ws}:setting:{key}`
- `apps/api/src/api/routes/workspace_settings.py` — NEW `APIRouter(prefix="/workspace-settings")`: GET list, GET /{key}, PUT /{key}, DELETE /{key}; `require_permission(WORKSPACE_READ/UPDATE)`; parse/validate; audit `workspace_setting.updated/deleted`
- `apps/api/src/main.py` — include_router
- `apps/api/src/settings.py` — add `agent_runner_driver`, `agent_runner_root`, `agent_mcp_enabled`, `agent_cost_table`, `agent_permission_ttl` defaults (global fallbacks)
- `apps/web/src/pages/settings/workspace/registry.ts` — add two sections: `agents-general` (order 60) + `agents-sandbox` (order 61), permission `workspace:read`
- `apps/web/src/pages/settings/workspace/sections/AgentsGeneralSection.tsx` — NEW: form default_model, default_runner Select (local/vercel/__none__), memory switch, permission TTL number
- `apps/web/src/pages/settings/workspace/sections/AgentsSandboxSection.tsx` — NEW: vercel team id + token (password, write-only), runner timeout
- `apps/web/src/App.tsx` — add two nested routes under `settings/workspace`
- `apps/api/tests/test_workspace_settings.py` — NEW: CRUD, 422 unknown key/enum, sensitive masked, 403 editor cannot PUT, cross-workspace 404

## Tasks & Acceptance

- [ ] model + __init__ + migration 0008
- [ ] settings.py global defaults
- [ ] service (validation + SecretStore)
- [ ] routes + main registration
- [ ] frontend registry + 2 sections + App route wiring
- [ ] tests

**AC:**
- `alembic upgrade head` creates `workspace_settings` with UQ; downgrade drops.
- `PUT /workspace-settings/agents.default_runner {"value":"vercel"}` → 200; GET list shows it; `PUT {"value":"docker"}` → 422.
- `PUT vercel_token {"value":"s3cr3t"}` → stored via SecretStore, GET returns `has_value:true` not plaintext, `DELETE` removes.
- Editor (no workspace:update) PUT → 403; GET → 200.
- UI: `/settings/workspace/agents-general` renders, save toasts, value persists on reload.

## Verification

- `cd apps/api && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
- `uv run pytest tests/test_workspace_settings.py -q && uv run pytest -q`
- `cd apps/web && npm run build`
