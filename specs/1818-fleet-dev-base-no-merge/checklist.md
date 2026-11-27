# Checklist: #1818 plan quality

- [x] CHK001 Are AC-1–AC-4 measurable? Yes — each is a named grep in `docs/FLEET.md` with pass/fail output.
- [x] CHK002 Is AC-5 measurable? Yes — `make label-contract` (`Makefile:144`, CI job `ci.yml:122`) exits 0/non-0.
- [x] CHK003 Does every FR (FR-001–FR-009) have at least one task? Yes — FR-001→T002, FR-002/003/004→T003, FR-005→T003 (+T006 sweep), FR-006→T003 (untouched) + T008 trace, FR-007→T004, FR-008→T005, FR-009→T009.
- [x] CHK004 Does every AC (AC-1–AC-8) appear in at least one task? Yes — AC-1→T001/T002/T007, AC-2→T001/T003/T006/T007, AC-3→T001/T003/T006/T007, AC-4→T001/T004/T007, AC-5→T001/T005/T007, AC-6→T008, AC-7→T008, AC-8→T009.
- [x] CHK005 Is the 5th file (`scripts/check-label-contract.sh`) justified, not scope creep? Yes — AC-5 is unsatisfiable without it: rule 3 pins `agent:merge` in the starts-no-work list, contradicting FR-008. Recorded as a plan decision for plan-check.
- [x] CHK006 Does the plan keep the high-risk path unchanged (FR-006)? Yes — T003 explicitly excludes step 3 and §6; T008 traces (not alters) it.
- [x] CHK007 Is the `@me` check correctly excluded? Yes — spec Out-of-Scope assigns it to piece 10 (autopilot prompts); no task touches `@me` queries.
- [x] CHK008 Is area context reported missing? Yes — no `.agents/areas/` directory exists and the item carries no `area:` label; spec scoped from the files triage named.
- [x] CHK009 Does the template edit satisfy the template grep contract (`^Area: ` line-start, not bold)? Yes — T004 requires plain line-start machine-read lines.
- [x] CHK010 Is the sequencing gate (FR-009/AC-8, owner comment, depends-on #1817) a build task, not just prose? Yes — T009 labels the PR `needs-human` and forbids merging before piece 5.
- [x] CHK011 (revise F1) Is the 5th-file script change covered without changing spec requirements? Yes — T005 + plan Approach step 5 cover it; round-1 `q-label-script` was unanswered so taken as Yes, and a round-2 non-blocking question records the spec-FR gap for the spec owner instead of editing the spec.
- [x] CHK012 (revise F2) Do plan.md/tasks.md/checklist.md exist with explicit T↔FR/AC mapping? Yes — all three files committed next to spec.md; CHK003–CHK004 trace every FR and AC to a task.
- [x] CHK013 (revise F3) Is the `agent:done` fate decided? Yes — approval keeps `agent:done` alongside `agent:merge` (step-1 skip list already excludes it; high-risk path precedent; contract-safe since `agent:done` is in the consumed table); pinned in Approach step 2, T003 and T006.
- [x] CHK014 (revise F4) Is the stale default-branch parenthetical gone? Yes — plan states base `main` per the strategy document without claiming it is the default.
