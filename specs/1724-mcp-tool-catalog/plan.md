# Plan: MCP tool catalog from FastAPI routes (#1724)

Spec: `specs/1724-mcp-tool-catalog/spec.md` (Status: Clarified). No `agent:plan-check`
revise verdict exists; this is a fresh plan. No code is written by this stage.

## Approach

Add one pure builder module plus one test module. The builder takes the
assembled `FastAPI` app and returns a list of plain tool records; it performs
no I/O, no auth, and no transport. It reads route metadata from `APIRoute`
objects and parameter/body schemas from `app.openapi()`, so `Depends`-injected
arguments (db sessions, principals, containers) never leak into tool schemas —
FastAPI already omits them from the OpenAPI document. Using the generated
OpenAPI document instead of signature introspection is the whole trick: path,
query and body shapes, required flags and `$ref`s come from one source the
framework keeps correct.

- **Scope**: iterate `app.routes`, keep only `fastapi.routing.APIRoute`
  instances whose `path` starts with `/api/v1` (the `API` prefix set in
  `apps/api/src/main.py`). Everything else (root `/`, mounted sub-apps,
  `APIWebSocketRoute` such as `/api/v1/ws`) is skipped, never raising.
- **Name**: `route.operation_id` when set, else a slug of lowercase method
  plus path template (e.g. `post /api/v1/workspaces` → `post_api_v1_workspaces`).
  No route sets `operation_id` today, so the fallback does the real work.
  Deduplicate with a numeric suffix (`…_2`, …) so two routes never collide.
- **Description**: `route.summary`, then `route.description`, then the endpoint
  `__doc__`, then a generated `"<METHOD> <path>"` placeholder.
- **inputSchema**: one `{"type": "object", "properties": {...}}` combining the
  OpenAPI `parameters` with `in: path` / `in: query` and the
  `application/json` request body schema. Every `$ref` is resolved against
  `openapi()["components"]["schemas"]` recursively, with a visited-set so a
  self-referencing model terminates as a finite schema. Routes with no
  parameters yield `properties: {}`.
- **Name-clash rule** (spec leaves this to plan): a name shared across
  path/query/body keeps one property; precedence is **path > query > body**,
  documented in the module. This cannot silently drop distinct meanings in
  practice: FastAPI binds one function argument per name, so a path and a
  query parameter with the same name are already the same value.
- **Dispatch record**: each tool carries the exact `route.methods` entry and
  `route.path` template (one tool per method when a path serves several).
- **Exclusion**: one explicit set of path prefixes/paths in the catalog module
  covering the AC-3 categories — credential handling under `/api/v1/auth`
  (`register`, `login`, `refresh`, `logout`, `forgot-password`,
  `reset-password`, `change-password`, `verify-email`, `resend-verification`,
  `sessions/*`, `2fa/*`; all confirmed in `apps/api/src/api/routes/auth.py`),
  OAuth (`/api/v1/auth/oauth/.../authorize`, `.../callback`, `/token`;
  confirmed in `apps/api/src/api/routes/oauth.py`), the WebSocket route
  (already skipped as non-`APIRoute`, listed anyway as belt-and-braces), and
  the future MCP endpoint path (`/api/v1/mcp*`, owned by #1725, reserved here
  so ordering with that issue does not matter). Plus the per-route opt-out:
  `openapi_extra={"x-mcp-exclude": True}` on the decorator. Every route not
  excluded is included, so new routers appear with no change.
- **Purity** (FR-008): synchronous function of the app object; testable
  against a minimal in-test `FastAPI()` app, no database, no lifespan.

New files live in confirmed directories: module next to
`apps/api/src/api/deps.py` / `crud.py`; tests next to the existing
`test_*.py` in `apps/api/tests/` (asyncio_mode is `auto` per
`apps/api/pyproject.toml`, so plain `async def test_…` matches house style).

## Files to change

- `apps/api/src/api/mcp_catalog.py` (new): `EXCLUDED_MCP_PATHS` set,
  `OPT_OUT_KEY = "x-mcp-exclude"`, `build_tool_catalog(app)` returning a list
  of tool records (`name`, `description`, `inputSchema`, `method`,
  `pathTemplate`), plus `$ref`-resolution and slug/dedupe helpers.
- `apps/api/tests/test_mcp_catalog.py` (new): tests-first module. A minimal
  in-test `FastAPI` app with an extra router (path + query + JSON-body params
  via a Pydantic model to exercise `$ref`), one opted-out route, and a
  duplicate-name pair; plus full-app tests importing `app` from `src.main`
  (same pattern as `apps/api/tests/conftest.py`) asserting tool count equals
  the eligible-route count and that excluded categories are absent.

## Data and contract changes

None. No models, migrations, settings, env vars, dependencies, or API routes
change. The only contract is the new in-process return type consumed later by
#1725 (transport) and #1726 (permission pruning, fed by #1723).

## Test plan

Per AC, tests written first (fail before the module exists):

- AC-4: test-router routes appear as tools with no catalog change; the
  `x-mcp-exclude` route does not; a route with path + query + body params
  produces the expected merged `inputSchema` (required flags preserved,
  `$ref` to the body model inlined).
- AC-1: against the full app, tool count equals the eligible `APIRoute` count
  and every tool has a unique name, a non-empty description and a valid
  JSON-Schema `inputSchema`.
- AC-2: sampled tools record the exact method and path template, including one
  path served by two methods.
- AC-3: `login`, `register`, `refresh`, `logout`, OAuth callback, `2fa/*` and
  `/ws` routes are absent; a newly added test router is present.
- Edge cases from the spec: duplicate-name dedupe, empty-params empty object,
  self-referential body model terminates, multi-method path yields one tool
  per method, non-`APIRoute` entries skipped.
- Smoke: `cd apps/api && uv run --extra dev pytest tests/test_mcp_catalog.py -q`
  (smallest real run of the new artifact; no DB needed for the unit tests,
  full-app tests reuse the existing sqlite conftest setup).

## Risks

- `app.openapi()` cost on a large app — negligible (FastAPI caches it) and
  test-only/full-app call sites call it once per build.
- Tool names shift if `operation_id`s are added later — inherent to the
  spec'd scheme; names are slugs, and consumers (#1725) resolve at startup.
- Exclusion list drifts as auth routes are added — mitigated by
  default-include plus a test asserting the excluded categories stay absent.
- Full-app import needs the conftest env setup — already handled by
  `apps/api/tests/conftest.py`; pure unit tests avoid it entirely.

## Rollback

Delete the two new files (or revert the single commit). No migration, config,
or existing code changes, so nothing else can break.

Skipped: SDK/packaging changes, MCP transport (#1725), auth/pruning (#1723,
#1726), docs (#1727) — all out of scope per spec. Not verified: running the
suite here (plan stage writes no code).
