# Tasks — #1795 Add web project extension seams

## Phase 1 — Setup and tests first

- [ ] T001 [AC-3] apps/web — baseline gate green before changes: `make web-build`, `make web-test`, `make web-typecheck`.
- [ ] T002 [AC-2] repo root — record pre-change `git status --short`; fix the expected diff set (3 template files + `apps/web/src/project/**`).

## Phase 2 — Implementation

- [ ] T003 [P] [AC-1,AC-4] apps/web/src/project/types.ts — NEW: demo entity type(s), no runtime imports.
- [ ] T004 [AC-1] apps/web/src/project/DemoPage.tsx — NEW: static `ListView` page typed by project types, gated with `useCan` on the project resource; no `dataProvider` call.
- [ ] T005 [AC-1] apps/web/src/project/index.ts — NEW: export `projectResources`, `projectRoutes`, `projectMenuItems`, `projectPermissionMap` (demo entries only; permission string already exists server-side).
- [ ] T006 [AC-2] apps/web/src/App.tsx — one-time: spread `projectResources` into `resources`; map `projectRoutes` inside the `RequireWorkspace` group.
- [ ] T007 [P] [AC-2] apps/web/src/components/AppLayout.tsx — one-time: project menu group spread in; export the `MenuItem` type.
- [ ] T008 [P] [AC-2] apps/web/src/providers/accessControlProvider.ts — one-time: spread `projectPermissionMap` into `PERMISSION_MAP`.
- [ ] T009 [AC-1] apps/web — verify demo renders, navigates, and gates both directions on the dev server (one Playwright chromium script per `AGENTS.md` browser rules, or manual with recorded result if docs don't require e2e).

## Phase 3 — Polish

- [ ] T010 [AC-2,AC-4] repo root — diff audit: only the 3 template files modified; `apps/web/src/types.ts` untouched; no project route path collides with a built-in route.
- [ ] T011 [AC-3] apps/web — full gate green with demo present: `make web-build`, `make web-test`, `make web-typecheck`.
- [ ] T012 [AC-5] PR body — carry exactly one release-note line: `Added apps/web/src/project/ extension seams (resources, routes, menu items, permission map, types).`
- [ ] T013 [polish] apps/web — smoke: dev-server load of `/` (zero-contribution parity, no empty groups or route errors) and the demo URL.
