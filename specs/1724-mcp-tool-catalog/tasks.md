# Tasks: MCP tool catalog from FastAPI routes (#1724)

## Phase 1 — Tests first

- [ ] T001 [AC-4] apps/api/tests/test_mcp_catalog.py — new test module on a minimal in-test FastAPI app: extra router routes appear as tools with no catalog change, `openapi_extra={"x-mcp-exclude": True}` route is absent, path+query+body route yields the expected merged inputSchema (fails before impl)
- [ ] T002 [AC-1, AC-3] apps/api/tests/test_mcp_catalog.py — full-app tests via `from src.main import app`: tool count equals eligible APIRoute count, every tool has unique name/description/valid schema, excluded categories (auth credentials, oauth callback, 2fa, ws) are absent

## Phase 2 — Implementation

- [ ] T003 [AC-1, AC-2] apps/api/src/api/mcp_catalog.py — builder core: iterate APIRoutes under `/api/v1`, stable unique name (operation_id else method+path slug with dedupe), description fallback chain, merged path+query+body inputSchema with recursive $ref resolution (cycle-safe), method+pathTemplate dispatch record
- [ ] T004 [AC-3] apps/api/src/api/mcp_catalog.py — exclusion: one explicit path set for credential/oauth/2fa/websocket/MCP routes plus `x-mcp-exclude` opt-out check; skip non-APIRoute entries; default-include everything else

## Phase 3 — Polish

- [ ] T005 [AC-1] apps/api/tests/test_mcp_catalog.py — edge-case tests: duplicate-name dedupe, no-param empty-object schema, self-referential body terminates, multi-method path yields one tool per method
- [ ] T006 [polish] run quality gate and smoke: `make api-lint` (ruff check + format check) and `cd apps/api && uv run --extra dev pytest tests/test_mcp_catalog.py -q`
