# Tasks: Route Access Introspection (#1723)

## Phase 1 — Setup and tests first

- [ ] T001 [P] [AC-3] apps/api/tests/test_route_access.py — write failing test: enumerate every app route under `/api/v1`, assert `route_access` returns a result without error; spot-check `apikey:create` (API-key create), session-only (`/me` routes), deployment-admin (`/admin/*`)

## Phase 2 — Implementation

- [ ] T002 [AC-1] apps/api/src/api/deps.py — expose permission string on `require_permission` / `require_key_permission` checkers and identifiable markers on `require_session_user` / `require_superuser`; no logic change
- [ ] T003 [AC-2] apps/api/src/api/route_access.py — add `route_access(route)` walking the route dependant tree; return permission(s), session-only, deployment-admin, workspace requirement; surface unrecognized checks instead of reporting public
- [ ] T004 [AC-4] apps/api/tests/ (existing suite, unchanged) — run `make api-test`; confirm all pass with identical authorization outcomes

## Phase 3 — Polish

- [ ] T005 [polish] apps/api/src/main.py (smoke only, no edit) — import `src.main:app` and count `/api/v1` routes; run `make api-lint` and full `make api-test` quality gate
