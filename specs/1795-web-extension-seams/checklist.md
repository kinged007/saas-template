# Checklist — #1795 Add web project extension seams

- [x] CHK001 Does every AC (AC-1..AC-5) appear in at least one task? (T001..T012 cover all five.)
- [x] CHK002 Does every task name an AC or a polish purpose? (T013 is labelled polish; all others carry AC tags.)
- [x] CHK003 Is AC-2 measurable? (Yes: `git diff --name-only` compared against the T002 expected set; T010 audits it.)
- [x] CHK004 Do the seam contracts use only confirmed paths and exports? (Confirmed by read: `resources` array and `RequireWorkspace` group in `App.tsx`; `SIDEBAR_GROUPS` + permission filter in `AppLayout.tsx`; `PERMISSION_MAP` + default-allow in `accessControlProvider.ts`; `ListView`/`useCan` pattern from `ApiKeysPage.tsx`; `LucideIcon` menu-item type.)
- [x] CHK005 Does the plan add no dependency, backend, migration, config, or env change? (None; web-only, static demo, existing permission string.)
- [x] CHK006 Is the unit-test scope honest about `node --test` limits? (Yes: no unit import of the `.tsx`-referencing seam package per `AGENTS.md`; gate is existing-suite-green plus `tsc`, matching the untested settings registries precedent.)
- [ ] CHK007 Does the demo gate on an already-existing server-side permission string? (Build confirms against the roles seed; fallback proves render/menu only — recorded as risk.)
- [x] CHK008 Is the zero-contribution edge covered? (Existing empty-group filter + unchanged defaults; T013 smoke-loads `/`.)
- [x] CHK009 Is the no-silent-route-override rule stated? (Namespaced `project-*` paths + static collision check in T010.)
- [x] CHK010 Is Gate 2 satisfied (one area = web; single release-note line quoted in plan and T012)? (Yes; Gate 3 exception rationale recorded in plan Approach.)
- [ ] CHK011 Do only the 3 template-owned integration points change? (Build proves via diff audit in T010.)
- [ ] CHK012 Is `src/types.ts` untouched with demo types resolving from `project/types.ts`? (Build proves via diff + `tsc` in T010/T011.)
