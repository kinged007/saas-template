# Plan: Route Access Introspection (#1723)

Source: `spec.md` in this directory (Status: Clarified; no `plan-check revise` verdict to address).
Area context was missing: no `.agents/areas/` index exists in this checkout, so entry points were found directly
(`apps/api/src/api/deps.py`, `apps/api/src/main.py`, `apps/api/src/api/routes/`).

## Approach

Attach data, change no behaviour. In `apps/api/src/api/deps.py` set a readable attribute on each gate checker
(the closures returned by `require_permission(p)` / `require_key_permission(p)` get `p`; `require_session_user` /
`require_superuser` get an equivalent marker), without touching any allow/reject logic. Add one new module
`apps/api/src/api/route_access.py` with `route_access(route: APIRoute)` that recursively walks the route's
`dependant` tree (`route.dependant` plus nested sub-dependants, which is where `Depends(...)` gates live after
FastAPI builds the app) and classifies what it finds: permission attributes, session-only marker,
deployment-admin marker, and workspace requirement (`get_current_workspace_id` = required,
`get_optional_workspace_id` = conditional, neither = not required). Anything authorization-relevant it does not
recognize (e.g. `require_target_profile_update`, `can_target_profile_update`, `resolve_membership`) is reported
as unrecognized, never as public — fail-closed per FR-005. New module goes under `api/` rather than a new `mcp/`
package because `ls` confirms `apps/api/src/mcp/` does not exist and one function does not justify a package.

Why this shape: attributes on the existing closures are the smallest change that makes gates readable from
`app.routes` (no registry, no decorator migration across 13 route files); a single tree-walking query covers
gates applied indirectly through composed dependencies per FR-004.

## Files to change

- `apps/api/src/api/deps.py` — add introspection attributes to the checkers returned by `require_permission`
  (line ~327) and `require_key_permission` (line ~279), and equivalent identifying markers for
  `require_session_user` (line ~119) / `require_superuser` (line ~148). Logic unchanged.
- `apps/api/src/api/route_access.py` — NEW: `route_access(route: APIRoute)` returning required permission(s),
  session-only flag, deployment-admin flag, workspace requirement, plus unrecognized checks. No existing file
  is modified for this.
- `apps/api/tests/test_route_access.py` — NEW: enumerates every route of the app under `/api/v1` (routers are
  mounted with `prefix=API` where `API = "/api/v1"` in `apps/api/src/main.py`), asserts a result without error,
  spot-checks `apikey:create` on the API-key create route, session-only on `/me`-family routes, and
  deployment-admin on `/admin/*` routes.

## Data and contract changes

None for persisted data, schemas, config, migrations, or dependencies. Additive-only public interface: one new
function (`route_access`) and new runtime attributes on the four gate callables. No route's authorization outcome
changes (FR-006 / AC-4).

## Test plan

- First: write `test_route_access.py` (enumeration over all `/api/v1` routes + three spot checks) and watch it
  fail (no `route_access`, no gate attributes) — covers AC-1/AC-2/AC-3.
- Then: implement gate attributes (AC-1) and `route_access` (AC-2) until the new test passes (AC-3).
- AC-4: run the existing backend suite unchanged: `make api-test` (from `Makefile`; CI job `api-test` in
  `.github/workflows/ci.yml` runs the same `pytest`). Confirm identical allow/reject outcomes; no existing test
  file is edited.
- Smoke test: `cd apps/api && uv run python -c "from src.main import app; print(len([r for r in app.routes if getattr(r, 'path', '').startswith('/api/v1'))]))"` —
  the documented artifact (`src.main:app`, served by `make api`) imports and exposes its `/api/v1` routes.
- Quality gate: `make api-lint` (`ruff check` + `ruff format --check`, same as CI `api-lint` job) and `make api-test`.

## Risks

- Auth-adjacent code: a wrong attribute value (not wrong logic, which is untouched) would mislead the #1724/#1726
  consumers into pruning a reachable tool or exposing an unreachable one. Mitigated by spot checks plus the
  fail-closed unrecognized bucket.
- Incomplete tree walk: gates hidden behind composed/nested dependencies could be missed. Mitigated by FR-004
  recursion plus the every-route enumeration test.
- Optional-workspace confusion: routes using `get_optional_workspace_id` (user-scoped for sessions,
  workspace-scoped for keys) must report conditional, not required/not-required. Covered by an explicit branch
  in `route_access`.
- Wildcard (`*`) permissions are reported as held, not expanded (spec edge case).

## Rollback

Revert the `deps.py` attribute lines and delete the two new files. No migration, no data, no config involved;
authorization logic is never touched so rollback restores the exact prior behaviour.
