# Checklist: promote.yml plan quality

- [x] CHK001 Does every AC appear in at least one task? (AC-1→T005/T006, AC-2→T005/T007, AC-3→T002/T008, AC-4→T002/T008, AC-5→T003/T009, AC-6→T004/T010, AC-7→T005/T011, AC-8→T005/T011, AC-9→T001/T012/T013 — verified against tasks.md)
- [x] CHK002 Is AC-2 measurable? (Yes: staging-move job has needs: on both verifier jobs — grep; both called workflows check out inputs.sha — already confirmed present in ci.yml and e2e.yml in this checkout)
- [x] CHK003 Are all named files confirmed to exist or be correctly new? (ci.yml, e2e.yml, merge-queue.yml, branch-guard.yml, scripts/branch-guard.test.sh, scripts/release-notes.sh, Makefile release-notes target all confirmed via ls/grep; promote.yml, promote.sh, promote.test.sh are new and non-colliding)
- [x] CHK004 Does the plan avoid editing ci.yml/e2e.yml call contracts? (Yes: both already accept workflow_call sha and check out inputs.sha in every job; only a new self-test job is added to ci.yml)
- [x] CHK005 Does every task name an AC or a polish purpose, with no extra scope? (Verified: no tagging, no rulesets, no release-candidate work — all out of scope per spec)
- [x] CHK006 Does the workflow land on the right branch first? (Yes: on dev per the issue sequencing note and spec clarification; dev is the current default so schedule fires)
- [x] CHK007 Which label routes the blocked-promotion issue — agent:triage (CI-CD.md §4.5 step 3, exists in repo) or loop-triage (spec clarification, does not exist as a label)? Resolved: agent:triage (plan-check F-01); spec clarification corrected in build.
- [x] CHK008 Can the self-test run hermetically? (Yes: stubbed gh + fixture git repo, same as branch-guard.test.sh; no network needed)
- [x] CHK009 Is concurrency handled? (Yes: concurrency group promote serializes overlapping scheduled/manual runs — spec edge case)
- [x] CHK010 Is the smoke test the smallest real run? (Yes: bash scripts/promote.test.sh locally, no network)
