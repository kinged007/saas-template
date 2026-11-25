# Plan — #1795 Add web project extension seams

Source: `specs/1795-web-extension-seams/spec.md` (Status: Clarified). Requirements taken from the
spec; no spec rewrite. Area context: missing — no `.agents/areas/` index exists and the issue
carries no `area:*` label, so code was explored directly (`App.tsx`, `AppLayout.tsx`,
`accessControlProvider.ts`, `types.ts`, settings-registry precedent, Makefile targets).

## Approach

Ship a project-owned package `apps/web/src/project/` that owns every per-page addition, consumed
by three one-time spreads in template-owned files. Data-shaped contributions (`resources`,
menu items, permission map) spread as values; routes spread as data (`{ path, element }`)
mapped to `<Route>` inside the existing `RequireWorkspace` guard, since the demo gates on an
existing workspace permission (frontend-only, one-area-per-change per ADMISSION Gate 2).

- `project/index.ts` exports `projectResources`, `projectRoutes`, `projectMenuItems`,
  `projectPermissionMap` (demo entries only).
- `project/types.ts` holds the demo entity type(s); `project/DemoPage.tsx` is a static
  `ListView` page (hardcoded rows, no `dataProvider` call, so no backend impact) gated with
  `useCan` on the project resource, following the canonical `ListView` + `useCan` pattern
  from `ApiKeysPage.tsx`.
- `App.tsx`: `...projectResources` in the `resources` array; `projectRoutes.map(...)` inside
  the `RequireWorkspace` group. `AppLayout.tsx`: project menu group spread in (the existing
  all-filtered-out group filter keeps the zero-contribution render unchanged); export the
  local `MenuItem` type as part of the one-time edit. `accessControlProvider.ts`:
  `...projectPermissionMap` into `PERMISSION_MAP` (demo declares a real entry so gating is
  proven, not default-allowed).
- Precedent: the settings-registry pattern (`registry.ts` + map to `<Route>` in `App.tsx`).

Why this shape: fewest moving parts, no new dependency, no plugin/hook framework. The
indirection removes an edit point per page rather than adding one, which matches the
ADMISSION Gate 3 exception (say so in the PR). `tsc` enforces the seam contracts.

## Files to change

- NEW `apps/web/src/project/types.ts` — demo entity type(s), no runtime imports (AC-1, AC-4).
- NEW `apps/web/src/project/DemoPage.tsx` — static demo page typed by project types (AC-1).
- NEW `apps/web/src/project/index.ts` — the four seam exports, demo entries only (AC-1).
- `apps/web/src/App.tsx` (one-time) — spread `projectResources`; map `projectRoutes` inside
  `RequireWorkspace` (AC-2).
- `apps/web/src/components/AppLayout.tsx` (one-time) — project menu group + export `MenuItem`
  type (AC-2).
- `apps/web/src/providers/accessControlProvider.ts` (one-time) — spread `projectPermissionMap`
  into `PERMISSION_MAP` (AC-2).
- `apps/web/src/types.ts` — must stay untouched, verified by diff (AC-4).

## Data and contract changes

New TypeScript-only contracts: the four seam exports plus the project entity types. No backend,
schema, migration, config, env-var, or dependency changes. Route rule: project paths are
namespaced (`project-*`) and must not collide with a built-in path (static check at build;
no silent override per spec edge cases).

## Test plan

- Baseline first: `make web-build`, `make web-test`, `make web-typecheck` green before changes
  (commands from `Makefile`; `build` = `tsc --noEmit` + `vite build`, `test` = `node --test`
  per `apps/web/package.json`).
- AC-1: build green; dev-server load of the demo URL as a permitted user renders with its
  sidebar entry; as an unpermitted user it is hidden/denied with built-in gated-page semantics.
- AC-2: `git diff --name-only` shows at most the three template files modified, plus new files
  only under `apps/web/src/project/`.
- AC-3: `make web-build` and `make web-test` pass unmodified with the demo present.
- AC-4: diff shows `apps/web/src/types.ts` unmodified; the demo imports its entity type from
  `project/types.ts` (`tsc` enforces resolution). No new unit-test file imports the seam
  package: `node --test` cannot load `.tsx` or the `@/` alias (per `AGENTS.md`), and the seam
  `index.ts` references the demo component — existing-suite-green plus `tsc` is the honest
  gate here, consistent with the untested settings registries already in the repo.
- AC-5: PR body carries exactly the release-note line (build-stage task, quoted below).
- Smoke test: `make web-build` green plus dev-server loads of `/` (zero-contribution parity:
  no empty groups, no route errors) and the demo URL.

## Risks

- Permission-string choice must exist server-side and differ across roles to prove both
  gating directions; fallback (`workspace:read`-class string) proves render/menu only.
  Build stage confirms against the roles seed.
- The seam `index.ts` references a `.tsx` component, so it stays outside `node --test`
  scope by design (see Test plan); gating is proven by build + navigation check instead.
- Workspace-free project pages later must map outside `RequireWorkspace`; one comment line at
  the mapping site records this so the demo's placement is not copied blindly.

## Rollback

Revert the three one-time edits and delete `apps/web/src/project/`; build and tests return to
baseline. No migration or persisted-data impact, so nothing else to unwind.

## Assumptions

Demo gates on an already-existing workspace permission (no backend change). Whether the demo
is kept as the canonical example or removed before merge is the reviewer's call (per spec).
Release-note line for the PR body: `Added apps/web/src/project/ extension seams (resources,
routes, menu items, permission map, types).`
