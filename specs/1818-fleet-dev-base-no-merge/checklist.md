# Checklist: #1818 plan quality

- [x] CHK001 Are AC-1–AC-4 measurable? Yes — each is a named grep in `docs/architecture/COMPLIANCE-CHECKLIST.md:19-22` with pass/fail output.
- [x] CHK002 Is AC-5 measurable? Yes — `make label-contract` (`Makefile:144`, CI job `ci.yml:122`) exits 0/non-0.
- [x] CHK003 Does every FR (FR-001–FR-009) have at least one task? Yes — FR-001→T002, FR-002/003/004→T003, FR-005→T003 (+T006 sweep), FR-006→T003 (untouched) + T008 trace, FR-007→T004, FR-008→T005, FR-009→T009.
- [x] CHK004 Does every AC (AC-1–AC-8) appear in at least one task? Yes — AC-1→T001/T002/T007, AC-2→T001/T003/T006/T007, AC-3→T001/T003/T006/T007, AC-4→T001/T004/T007, AC-5→T001/T005/T007, AC-6→T008, AC-7→T008, AC-8→T009.
- [x] CHK005 Is the 5th file (`scripts/check-label-contract.sh`) justified, not scope creep? Yes — AC-5 is unsatisfiable without it: rule 3 pins `agent:merge` in the starts-no-work list, contradicting FR-008. Recorded as a plan decision for plan-check.
- [x] CHK006 Does the plan keep the high-risk path unchanged (FR-006)? Yes — T003 explicitly excludes step 3 and §6; T008 traces (not alters) it.
- [x] CHK007 Is CICD-14 correctly excluded? Yes — spec Out-of-Scope assigns it to piece 10 (autopilot prompts); no task touches `@me` queries.
- [x] CHK008 Is area context reported missing? Yes — no `.agents/areas/` directory exists and the item carries no `area:` label; spec scoped from the files triage named.
- [x] CHK009 Does the template edit satisfy the CICD-13 grep contract (`^Area: ` line-start, not bold)? Yes — T004 requires plain line-start machine-read lines.
- [x] CHK010 Is the sequencing gate (FR-009/AC-8, owner comment, depends-on #1817) a build task, not just prose? Yes — T009 labels the PR `needs-human` and forbids merging before piece 5.
