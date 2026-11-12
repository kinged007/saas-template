# Checklist — #1618

- [x] CHK001 Is the missing spec stated in the plan header, with the source of the requirements?
- [x] CHK002 Is the cause backed by API output that a reviewer can re-run (AC-1)?
- [x] CHK003 Are the alternative causes in the issue (fork path, branch protection, `auto/*` push path, runners) each ruled out with evidence?
- [x] CHK004 Is the config change exact (one command, one workflow id) (AC-2)?
- [x] CHK005 Is AC-3 measurable (specific API call, threshold, job name)?
- [x] CHK006 Does the guard require a push made after the re-enable, so an old head cannot pass it?
- [x] CHK007 Does AC-4 keep the flake fix out of this PR, as the owner's comment requires?
- [x] CHK008 Is the flake linked to the existing tracking issue (#1508) instead of a duplicate?
- [x] CHK009 Does every AC have at least one task, and every task an AC or polish purpose?
- [x] CHK010 Are all named files and ids confirmed (`AGENTS.md`, `.github/workflows/ci.yml`, `apps/web/e2e/signin-return-to.spec.ts`, workflow id 363399628, #1508)?
- [x] CHK011 Are the spend risk of re-enabling and the drift risk of six weeks without CI stated?
- [x] CHK012 Is rollback a single command plus a revert?
- [x] CHK013 Is "Data and contract changes" accurate (one repo setting, no code or schema)?
