# Checklist: branch-guard plan (#1838)

- [x] CHK001 Is each AC measurable as a red/green run plus issue behaviour? Yes: AC-1..AC-7 name the run colour and issue content; AC-8..AC-10 name the suite, grep, and PR evidence.
- [x] CHK002 Does every FR have a task? Yes: FR-001/T007, FR-002/T005 (+T002), FR-003+FR-004/T006 (+T003), FR-005/T006 (+T004), FR-006/T005 (+T004), FR-007/T007, FR-008/T001..T004, FR-009/T009.
- [x] CHK003 Does every AC appear in at least one task? Yes: AC-1..AC-6 in T002..T006, AC-7 in T007, AC-8 in T001/T009, AC-9 in T007/T008, AC-10 in T009.
- [x] CHK004 Is pushed-range-only checking specified, excluding historic commits 462dfea2d/2f1e27fd7? Yes: plan uses before..after first-parent listing; T004 proves scoping; empty range passes.
- [x] CHK005 Is first-run verification specified (AC-10)? Yes: base dev, Area: infra squash message passes its own rule; T009 records the green run or the alternative.
- [x] CHK006 Are edge cases covered without scope creep? Yes: deletion fails, empty range passes, merge-on-dev fails, ancestor approximation and concurrency limits recorded as risks; product-loop audit and rulesets stay out of scope per spec.
- [x] CHK007 Do tasks add nothing no AC or polish purpose needs? Yes: three new files only; no Makefile target, no checklist rewrite, no dependency; T010 is the repo quality gate.
- [x] CHK008 Are all named files and patterns confirmed? Yes via ls/grep: scripts/check-template-paths.sh + .test.sh precedent, scripts/merge_queue.py AREA_RE/VALID_AREAS, .github/workflows/ci.yml + merge-queue.yml, Makefile targets, COMPLIANCE-CHECKLIST.md CICD-29 line, needs-human label exists; branch-guard.yml and scripts/branch-guard.* are the new files this issue creates.
