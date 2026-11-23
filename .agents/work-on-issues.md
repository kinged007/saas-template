# Next-issue workflow

Pick up the next actionable piece of work and implement it. Run from the repo root. All `gh` commands assume the repo default (current directory) — never hardcode `repos/<owner>/<repo>`.

Work directly from the open-issue list. This workflow does not order by milestone.

## Process lifecycle and cleanup (MANDATORY)

Never finish a run with a process started by the agent still running. This includes the API/frontend stack, supervisors, watchers, and test servers. Stop every owned process on success, failure, cancellation, timeout, and every early `STOP` path. A timeout is only a safety net, not cleanup.

Run long-lived commands in the foreground when possible. If backgrounding is necessary, give the command a finite budget and record its PID. For example, on Linux:

```bash
timeout --signal=TERM --kill-after=15s 1h <command>
```

Browser automation is a separate concern: per `.agents/browser.md`, each script launches and closes its own chromium inside a `timeout`, so it leaves nothing behind.

Use a task-appropriate cap for the application stack as well. At cleanup, send `SIGTERM` to the exact supervisor or process you started, wait for it, then use `SIGKILL` only if it remains alive. Verify its children and the ports it owns. Never kill an unknown process or clear a port you did not open. Remove temporary PID/log/browser files. If cleanup cannot be verified, do not report completion.

## 1. List open issues, sorted by priority then age

Priority comes from three labels: `P0` (highest), `P1`, `P2` (lowest). Highest priority wins; within one priority, the oldest issue wins. An issue with no priority label sorts after every `P0`/`P1`/`P2` issue, ordered among the unlabelled group by age. If an issue carries more than one priority label, the highest one counts. The agent only reads these labels and never adds or removes them.

This single command returns the actionable issues already in that order:

```bash
gh issue list --state open --limit 100 \
  --json number,title,createdAt,labels \
  -q 'map(select(([.labels[].name] | any(. == "wontfix" or . == "needs-human" or . == "backlog" or . == "in-progress" or . == "review-in-progress" or . == "invalid" or . == "duplicate" or . == "agent:done")) | not))
      | map(. + {p: ([.labels[].name | select(. == "P0" or . == "P1" or . == "P2")] | sort | first // "UNSET")})
      | sort_by((if .p=="P0" then 0 elif .p=="P1" then 1 elif .p=="P2" then 2 else 3 end), .createdAt)
      | .[] | "#\(.number) | \(.p) | \(.createdAt) | \(.title)"'
```

Two details matter. The skip filter uses `any(... or ...)`, not `inside(...)`: `inside` is fed the label array as input and does not do what it looks like here, so an issue carrying `needs-human` alongside another label slips through the filter. The priority lookup takes `sort | first` over the matched labels so that an issue tagged both `P2` and `P0` ranks as `P0`.

If the three priority labels do not exist yet, every issue sorts as `UNSET` and the effective order is oldest first. That is correct but inert — ask the maintainer to label the backlog before relying on priority ordering.

## 2. Drop finished, invalid, or claimed issues

The step 1 query already excludes every issue labelled `wontfix`, `needs-human`, `backlog`, `in-progress`, `review-in-progress`, `invalid`, `duplicate`, or `agent:done`. `backlog` means deferred by a person — do not dispatch it. Never touch a skipped issue, even if open.

## 3. Find the next unblocked and related open issues

Work the step 1 list top to bottom. Its first entries are the highest priority and the oldest, so the first unblocked candidate is the one to take.

If a candidate carries the `agent:plan` label, post a brief issue comment saying planning is still pending and stop without making changes (the label was added after dispatch). Do not implement it.

For each remaining candidate in step 1 order, check blockers:

```bash
gh issue view <n> --json blockedBy \
  -q '.blockedBy.nodes[] | "\(.number) \(.state) \(.title)"'
```

Take issues with no blocker in `OPEN` state. Claim ONE issue; only claim more when they are related or similar to each other, and the more complex the issue, the fewer to claim at the same time. One admitted issue that serves the phase beats five that do not.
If every open issue is blocked by another open issue, stop and report that the backlog is drained or deadlocked.

## 3a. Claim every selected issue before work (MANDATORY)

The listing excludes `in-progress`, but re-check the selected issue immediately before claiming it. Once you select one or more issues, and before reading comments, posting a plan, starting the dev stack, or changing files, verify that `in-progress` is absent and add it to every issue you will work on:

```bash
gh issue view <n> --json labels -q '.labels[].name'
gh issue edit <n> --add-label in-progress
```

Run the command once per selected issue. If `in-progress` is already present, do not work on that issue; choose another. If adding a label fails, release any labels successfully added by this run and stop.

Keep the issue numbers that this run successfully claimed. On every exit path, release `in-progress` from each claimed issue. On a successful run, do not release it until the final commit and push have succeeded; on a blocked run, apply `needs-human` before releasing it:

```bash
gh issue edit <n> --remove-label in-progress
```

Never remove a label claimed by another agent. If no issue is claimed, there is nothing to release.

Do not add `agent:done` when releasing early. It marks finished work and is applied once, on the success path in step 10. An issue that stops at `needs-human` is not done, and one abandoned mid-implementation is not done; both stay without it so they can be picked up again.

## 3b. Apply admission Gate 0 before work (MANDATORY)

Read `docs/product/ADMISSION.md`, then assess every claimed issue against Gate 0: until the first release, only three kinds of change are built — work that delivers the update-path guarantee (VISION §4), a security fix, or a fix restoring already-documented behaviour.

An issue that fails Gate 0 but passes Gates 1–4 is deferred, not built. Defer it and move on to the next candidate — never stop the run on the first deferred issue:

```bash
gh issue comment <n> --body "Deferred: Gate 0 / <P0|P1|P2|unlabelled> — <one line: which of the three admitted kinds it is not, and the earliest release it waits for>"
gh issue edit <n> --add-label backlog
gh issue edit <n> --remove-label in-progress
```

An issue that fails Gate 0 and also fails a later gate gets that gate's verdict instead (Reject, or Maintainer via `needs-human`), then release `in-progress` and continue to the next candidate. Only an issue that passes Gate 0 proceeds to step 4.

## 4. Read the issue threads first, then plan, then post the plan

Read ALL existing comments on the issues BEFORE planning — some issues already carry a plan or steering notes that override the body:

```bash
gh issue view <n> --json title,body,comments,labels \
  -q '.title, .body, (.comments[] | "--- @\(.author.login) \(.createdAt) ---\n\(.body)")'
```

Treat comments as authoritative over the body where they conflict (newest wins). Comments may contain corrections, reproduction details, or scope changes that override the description. If an approved plan was posted, follow it. If a comment already contains a plan, adopt it unless the codebase has moved on, and say so in the posted plan.

If the task is already resolved, post an issue comment saying so, remove `in-progress` from every issue claimed by this run, and stop without making changes:

```bash
gh issue edit <n> --remove-label in-progress
```

Context to read:

- the repo's architecture docs; check `docs/` for related docs on the area being touched.
- the project's context map / wiki if present, then the source files it lists. Never plan from the wiki alone.
- check blast radius before touching widely-imported files.
- `docs/architecture/CONVENTIONS.md`: the plan's "Conventions touched" section lists the `CONV-<AREA>-NN` rule IDs the change touches, or `none`. A change that has to break a rule needs a `docs/product/DECISIONS.md` entry; that is an architectural change, so apply `needs-human` as below.
- Follow the repo's own instructions (tooling, make targets, no new dependencies without asking).
- Post the plan as an issue comment before writing code:

```bash
gh issue comment <n> --body "## Plan
...
### Related issues
...
### Files to touch
...
### Conventions touched
CONV-... IDs from docs/architecture/CONVENTIONS.md, or none
### Acceptance (from issue)
..."
```

If the plan is straightforward and follows existing code structure and architecture patterns, proceed with auto-approval. If the plan contains architectural changes or a significant shift in design, request human approval. Apply `needs-human`, remove `in-progress` from every issue claimed by this run, then STOP. Do not proceed. Repeat both commands for each claimed issue.

```bash
gh issue edit <n> --add-label needs-human
gh issue edit <n> --remove-label in-progress
```


## 5. Dev environment and seeded credentials

Start the stack with the repo's own dev command (see README / AGENTS.md / Makefile — never leave it running orphaned). The dev command usually installs deps, migrates, and seeds automatically.

Discover the seeded credentials yourself — they show in the dev startup output and live in the repo's seed script/fixtures.

Log in with a seeded account for manual/visual verification. If the task needs a different user shape, seed one following the repo's seed patterns or register through the UI — do not hardcode ad-hoc credentials in the codebase.

Browser: Playwright driving chromium, per `.agents/browser.md`. Read that file before any browser use. Any browser use MUST follow it — never obscura, never chrome-devtools. If `.agents/browser.md` is missing, follow the rules it would have contained: locate the frontend app and run from there, launch headless chromium per script inside a `timeout`, close it in the same script, and never install the browser globally. That file also covers the shared per-user browser cache, the seeded account, the observable-result assertion, and when a screenshot is not acceptable evidence.
## 6. Implement (claim already held)

Do not add the label again. The claim was acquired in step 3a before any work began.

Implement the posted plan, then run the repo quality gate (resolve from README / AGENTS.md / Makefile / CI workflows — at minimum lint, tests, and a build of every area touched).

Review your own diff (`git diff`) for correctness, regressions, and convention compliance before finishing.

## 7. Pre-PR testing gate (MANDATORY)

Before opening the PR, the agent MUST prove the change does not break the pipeline. If CI workflows exist (`.github/workflows/`), read them and manually run every check they run (lint, typecheck, tests, build) before submitting. If no CI exists, run the repo's full quality gate instead (see README / AGENTS.md — at minimum lint, tests, and a build of every area touched) and make sure all tests pass.

Do not open the PR while any of these fail. If a check fails, fix the cause (not the check) and re-run until green. Never submit a PR with a red gate and a promise to fix it after — the next session starts from pushed state, so a broken push poisons every session after it. If a check cannot be made green for reasons outside the change, document the failure in the PR body under Verification, apply `needs-human`, remove `in-progress` from every issue claimed by this run, and stop instead of submitting. Repeat both commands for each claimed issue:

```bash
gh issue edit <n> --add-label needs-human
gh issue edit <n> --remove-label in-progress
```

If the plan proves wrong mid-implementation, update the issue comment with what changed and why.

If implementation and testing succeed, submit a PR for the issue (push the branch first, see step 8). Explain in detail what the problem was, what was implemented, and how correctness was verified.

## 8. Open the pull request

Do not push directly to the PR's base branch. Resolve the base first (never assume) and open the PR from a per-issue branch against it:

```bash
BASE=$(gh repo view --json defaultBranchRef -q '.defaultBranchRef.name')
git checkout -b auto/<n>
git push -u origin auto/<n>
gh pr create --base "$BASE" --head auto/<n> --title "<summary>" --body "<body>"
```

The PR body must follow this structure — two-line bodies are not acceptable:

```markdown
Fixes #<n>.

## Summary
[one paragraph: what this PR does and why]

## Solution
[approach taken, key design decisions]

## Changes
- [file or area]: [what changed]

## Verification
- [checks run and their results]
```

Every section is required. Do not apply `agent:review` to the PR yourself; the human triggers the deep review when ready.

## 9. Post the closing issue comment

When done, post one detailed comment on the issue. A reader must understand what was done without reading the diff:

```bash
gh issue comment <n> --body "..."
```

Structure the comment as:

```markdown
## Summary
[one paragraph: outcome and approach]

## Changes
- [file or area]: [what changed and why]

## Verification
- [checks run and their results]

## Issues encountered
[problems hit and how resolved, or "None"]

PR: [link]
```

Every section is required; write "None" only when true. Do not compress this into a few lines.

Keep `in-progress` on every claimed issue until the final commit and push in step 10 succeed. Do not release the claim before then.

## 10. Commit and push before finishing (MANDATORY)

This overrides the `AGENTS.md` no-commit default: the agent MUST commit and push all work (code, tests, and the issue/PR comments are already remote) before finishing the session. Never leave work uncommitted or unpushed — the next session starts from the pushed state.

```bash
git add -A && git commit -m "<type(scope): summary>" && git push
# PR fixes: commit onto the PR branch and push so the PR updates
git push -u origin $(git branch --show-current)
```

After the final push succeeds, mark the work finished and release the claim. Run both commands for each issue claimed by this run:

```bash
gh issue edit <n> --add-label agent:done
gh issue edit <n> --remove-label in-progress
```

`agent:done` is what stops the next run from re-implementing a finished issue: step 1 skips it, and only a human closes the issue when they are satisfied. Without this label the issue stays open, unclaimed, and becomes the next run's first candidate. Apply it only after the push has actually landed.

Verify the push landed (`git status -sb` shows clean, `gh pr view <n>` shows the new commits). Before reporting done, verify that every claimed issue carries `agent:done` and no longer carries `in-progress`.
