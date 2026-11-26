# Checklist — #1893 plan quality

- [x] CHK001 Is AC-1 measurable? Yes — `git merge-base --is-ancestor v0.2.0 dev` (or `main` if #1880 lands), tasked in T001/T006/T011.
- [x] CHK002 Is AC-2 measurable without trusting the editor? Yes — sha256 of the `[0.1.0]` section before (T002) vs after (T005) must match; new entry dated and area-grouped.
- [x] CHK003 Is AC-3 unambiguous about `v0.1.0`? Yes — spec clarification leaves it as published; release notes state the decision + per-tag seed commits (T007).
- [x] CHK004 Does AC-4 forbid non-guide steps? Yes — QA follows `docs/UPGRADING.md` §§1–3 verbatim in a scratch dir; transcript with exit codes pasted in a comment (T008/T009).
- [x] CHK005 Does every AC appear in at least one task? Yes — AC-1: T001/T006/T011; AC-2: T002/T004/T005; AC-3: T001/T007/T011; AC-4: T003/T008/T009; AC-5: T010; AC-6: T008 (via the seeded update, per spec).
- [x] CHK006 Does every task name an AC or a polish purpose? Yes — T012 is the sole polish task (label-contract + status hygiene).
- [x] CHK007 Are tasks free of unconfirmed file/function names? Yes — all paths (`CHANGELOG.md`, `docs/UPGRADING.md`, `Makefile` targets, `scripts/release-notes.sh` avoided for content, `.github/workflows/ci.yml`, `TEMPLATE_PATHS`) confirmed with `ls`/`grep` during planning.
- [x] CHK008 Does the plan avoid redesigning the guide or the promotion pipeline? Yes — both are explicit Out of Scope; `docs/UPGRADING.md` is exercised, not edited; #1880 is a re-check condition, not work.
- [x] CHK009 Is the diverged-base pitfall addressed? Yes — plan and T004 forbid `git log v0.1.0..dev` for changelog content; entry is built from dev history of the seven slices.
- [x] CHK010 Is rollback safe and does it protect the published tag? Yes — pre-publish delete + revert; post-publish forward-fix only; `v0.1.0` never touched.
