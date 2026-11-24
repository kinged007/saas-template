# Checklist: source-guard plan (issue #1874)

- [x] CHK001 Is AC-1 measurable — does the self-test assert failed check, retarget to `dev`, and exactly one comment? Yes: T001 covers all three observables with the stubbed `gh` call log.
- [x] CHK002 Is AC-2 measurable — pass with no comment and no retarget? Yes: T001 asserts zero stub calls on the same-repo `staging` path.
- [x] CHK003 Is AC-3 measurable — PRs targeting `dev`/`staging` ignored? Yes: T001 plus the trigger-filter/job-`if` double layer in T006.
- [x] CHK004 Is AC-4 measurable — fork PR retargeted with failed check, including a fork branch named `staging`? Yes: T001/T004 call out the same-name fork edge case from the spec.
- [x] CHK005 Is AC-5 measurable — trusted-version evaluation and no PR-code execution? Yes: T002 asserts evaluation via the checked-in script; T010 re-verifies the final diff has no PR-head checkout.
- [x] CHK006 Is AC-6 measurable — named check selectable as required? Yes: T007 names workflow and job `source-guard` (greppable, per the test plan).
- [x] CHK007 Is AC-7 measurable — self-test passes locally and runs in CI? Yes: T001 scaffolds it, T008 wires it into `ci.yml` after the `release-notes` job, T011 runs it as the smoke test.
- [x] CHK008 Is AC-8 measurable — docs rule plus checklist item? Yes: T003 confirms anchors/ids first, T009 writes both lines with a grep verification command.
- [x] CHK009 Does every FR have a task? FR-001→T005/T006, FR-002→T004/T006, FR-003→T004/T005, FR-004→T006, FR-005→T002/T005/T010, FR-006→T007, FR-007→T001/T008, FR-008→T003/T009. Yes.
- [x] CHK010 Does every task name an AC or a polish purpose, with no unneeded tasks? Yes: T001–T009 each cite an AC; T010 cites AC-5; T011/T012 are the mandated smoke test and quality gate.
- [x] CHK011 Are all named files/functions confirmed — no invented paths? Yes: `.github/workflows/`, `scripts/branch-guard.sh`, `scripts/branch-guard.test.sh`, `.github/workflows/ci.yml`, `docs/architecture/CI-CD.md`, `docs/architecture/COMPLIANCE-CHECKLIST.md` all read via shell; new files reuse the confirmed `source-guard` / `source-guard.test.sh` / `source-guard.sh` names from the issue and spec.
- [x] CHK012 Does the plan avoid changing the spec's requirements? Yes: credential either/or resolved to `pull-requests: write` (least privilege, explicitly left to the plan stage by the issue/spec); rulesets stay out of scope; R-1 records the `FLEET_TOKEN` fallback.
