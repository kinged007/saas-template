# Checklist — #1817 merge-queue.yml (CI-CD piece 5)

- [x] CHK001 Is every AC measurable without human judgment? Yes: AC-1/2/4/5/6/12 are grep assertions from COMPLIANCE-CHECKLIST.md; AC-3/9/10/11 are unit-testable mappings; AC-7 is a dry-run with state diff; AC-8 is a test run.
- [x] CHK002 Does every FR have at least one task and every task name an AC or polish purpose? FR-001→T006, FR-002→T006, FR-003→T002/T003, FR-004→T002/T003, FR-005→T002/T003, FR-006→T002/T003, FR-007→T002/T003, FR-008→T004, FR-009→T004, FR-010/011→T005, FR-012→T004/T006, FR-013→T003/T007, FR-014→T001/T002; T007→AC-7, T008→polish.
- [x] CHK003 Is the advisory-approval tension resolved per the spec, not the checklist wording? Yes: FR-007 + resolved clarification (record-only, no mark change, no block) override CICD-24's "sets agent:review" phrasing; plan records this as a risk for the manual read.
- [x] CHK004 Does the plan avoid contradicting CI-CD.md's "lives on main"? Yes: the repo default branch is `dev` and `main` does not exist yet; the spec (FR-001) says "default branch", so the workflow lives on the default branch. Recorded as an assumption, not a spec change.
- [ ] CHK005 Has the build pinned and verified the exact platform sources for label-applied times, closing-issue references, and head-SHA reviews against the live API?
- [x] CHK006 Is at most one merge per run with skip-to-next-candidate on gate failure (except gate 1) stated in both plan and tasks? Yes (plan design points, T003).
- [x] CHK007 Are the piece 1/2/3 dependencies (FLEET_TOKEN secret, ci statuses, Area/Release-note inputs) explicit with loud-failure behavior? Yes (plan risks + rollback).
- [ ] CHK008 Does `make label-contract` still pass with the new workflow referencing `agent:*` labels (no doc change expected)?
- [x] CHK009 Is the implementation stdlib-only with no new dependencies, labels, or edits to existing files? Yes by construction; T008 verifies the file list.
- [x] CHK010 Are the spec edge cases (empty queue, gate-1 red, retargeted base, mid-queue conflict, moved head SHA, missing trailers, multiple linked issues, flaky green retry, concurrent delivery) covered? Yes: gates 1–6 + selection + retry/revert + concurrency group; maps 1:1 onto T002/T003/T005/T006 (spec edge-case section).
