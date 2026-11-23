# Review-PR workflow

Pick up the next open PR, review it, and either fix-and-stop or merge-and-close. Fix majors and minors, report, STOP — the next fresh session re-reviews. You can only merge and close a PR if all issues were fixed in a previous session. You cannot review, fix, and close in one session — if you fix issues in your session, hand off for a new review session to review and close. Run from the repo root. All `gh` commands assume the repo default (current directory) — never hardcode `repos/<owner>/<repo>`.

`backlog` means deferred by a person — never touch it. `in-progress` is the mandatory claim lock for this workflow; `review-in-progress` is also treated as claimed for compatibility. `needs-human` means blocked, and `agent:done` means reviewed, ready to merge, and no longer to be picked up by step 1. `agent:done` is applied on the approval path in step 7 — if a PR is approved but not yet merged, it must already carry it, otherwise step 1 will hand it to the next agent forever.

## Process lifecycle and cleanup (MANDATORY)

Never finish a run with a process started by the agent still running. This includes the API/frontend stack, supervisors, watchers, and test servers. Stop every owned process on success, failure, cancellation, timeout, and every early `STOP` path. A timeout is only a safety net, not cleanup.

Run long-lived commands in the foreground when possible. If backgrounding is necessary, give the command a finite budget and record its PID. For example, on Linux:

```bash
timeout --signal=TERM --kill-after=15s 1h <command>
```

Browser automation is a separate concern: per `.agents/browser.md`, each script launches and closes its own chromium inside a `timeout`, so it leaves nothing behind.

Use a task-appropriate cap for the application stack as well. At cleanup, send `SIGTERM` to the exact supervisor or process you started, wait for it, then use `SIGKILL` only if it remains alive. Verify its children and the ports it owns. Never kill an unknown process or clear a port you did not open. Remove temporary PID/log/browser files. If cleanup cannot be verified, do not report completion.

## Claim lock (MANDATORY)

After selecting an actionable PR and before reading its thread, starting the dev stack, reviewing, fixing, or doing any other work, the agent MUST re-check its labels and apply the claim label only if neither `in-progress` nor `review-in-progress` is present:

```bash
gh pr view <n> --json labels -q '.labels[].name'
gh pr edit <n> --add-label in-progress
```

If either label is already present, do not claim the PR; select another. If the add command fails, do not start work. Before every `STOP`, blocked/escalation exit, and final report, the agent MUST remove the label from the PR it claimed:

```bash
gh pr edit <n> --remove-label in-progress
```

Removing `in-progress` is mandatory even when the PR is blocked, already resolved, or the agent stops because of an error.

## 0. Dev environment and seeded credentials (read first)

Start the stack with the repo's own dev command (see README / AGENTS.md / Makefile — never leave it running orphaned). The dev command usually installs deps, migrates, and seeds automatically.

Discover the seeded credentials yourself — they show in the dev startup output and live in the repo's seed script/fixtures.

Log in with a seeded account for manual/visual verification (including the screenshots in step 4). If the task needs a different user shape, seed one following the repo's seed patterns or register through the UI — do not hardcode ad-hoc credentials in the codebase.

Browser: Playwright driving chromium, per `.agents/browser.md`. Read that file before any browser use. Any browser use MUST follow it — never obscura, never chrome-devtools. If `.agents/browser.md` is missing, follow the rules it would have contained: locate the frontend app and run from there, launch headless chromium per script inside a `timeout`, close it in the same script, and never install the browser globally.

## 1. Find the oldest open PR

Skip any PR labelled `wontfix`, `needs-human`, `backlog`, `in-progress`, `review-in-progress`, `invalid`, `duplicate`, or `agent:done` — never touch those, even if open. The rest are ordered oldest first, so the PR that has waited longest is reviewed first:

```bash
gh pr list --state open --limit 50 --search "sort:created-asc" \
  --json number,title,createdAt,labels \
  -q 'map(select(([.labels[].name] | any(. == "wontfix" or . == "needs-human" or . == "backlog" or . == "in-progress" or . == "review-in-progress" or . == "invalid" or . == "duplicate" or . == "agent:done")) | not))
      | .[] | "\(.number) | \(.createdAt) | \(.title)"'
```

`--search "sort:created-asc"` is what makes this oldest-first; without it `gh` returns the newest PR first. `--json` output preserves the order `gh` returned, and the `any(... or ...)` filter preserves that order too — it drops skipped PRs without reordering the rest. Do not use `inside(...)` for this filter: given the label array as input it lets a PR carrying a skipped label alongside another label through.

Take the first listed. If the list is empty, stop and report that no actionable PR exists. Otherwise re-check its labels and claim it only if neither `in-progress` nor `review-in-progress` is present:

```bash
gh pr view <n> --json labels -q '.labels[].name'
gh pr edit <n> --add-label in-progress
```

## 2. Read the PR thread first

Read the body, ALL comments, and ALL reviews BEFORE doing anything else — prior review verdicts and steering notes override a cold read:

```bash
gh pr view <n> --json title,body,comments,reviews,labels,mergeable,mergeStateStatus \
  -q '.title, .body, (.comments[] | "--- @\(.author.login) \(.createdAt) ---\n\(.body)"), (.reviews[] | "--- REVIEW @\(.author.login) \(.state) \(.submittedAt) ---\n\(.body)")'
```

Also fetch the diff (`--patch` into context only if small; otherwise summarise per-file):

```bash
gh pr diff <n> --patch
```

Treat the newest review/comment as authoritative where things conflict. If anything in the thread is ambiguous or the PR is conflicted beyond a trivial rebase, apply `needs-human`, release the claim, and STOP:

```bash
gh pr edit <n> --add-label needs-human
gh pr edit <n> --remove-label in-progress
```

## 3. Classify risk

A PR is **high-risk** if it touches any of:

- files owned in `.github/CODEOWNERS` (high-impact files, migrations, infra)
- auth, sessions, tokens, passwords, OAuth flows
- credential storage, encryption, secrets handling
- production config, ports, deployment (`infra/`, Docker, env templates)

High-risk PRs follow the same review-and-fix path below, but the agent must NEVER merge them. After review/fixes, apply `needs-human` for the merge decision and `agent:done` to record that the review is finished, remove `in-progress`, and STOP. Only the owner merges high-risk work:

```bash
gh pr edit <n> --add-label needs-human
gh pr edit <n> --add-label agent:done
gh pr edit <n> --remove-label in-progress
```

## 4. Review, unless a recent review already stands

If a review was submitted since the last code change (compare review `submittedAt` against the latest commit date), adopt its verdict instead of re-reviewing: majors already listed → go to step 5; approved → go to step 7 (or stop with `needs-human` if high-risk per step 3).

Otherwise review thoroughly against:

- the repo's architecture docs plus related `docs/`; the project's context map / wiki if present, then the actual source files; check blast radius before touching widely-imported files.
- Correctness, tests, error handling, security, migration safety. Classify every finding as **major** (blocks merge: bugs, data loss, security, broken tests, arch violations) or **minor/deferred** (nits, follow-ups, polish).

The agent MUST NOT use `gh pr review --request-changes`. To request changes, it MUST post a normal PR comment; this comment is the handoff that the next agent reads before acting. Post the review with this structure — every section is required:

```bash
gh pr comment <n> --body "$(cat <<'EOF'
# PR #<n> Review Summary

## Overview
[Brief description of what the PR does]

## Key Findings

### Strengths
[Major positive aspects]

### Critical Issues
[Must resolve before merge]

### Recommendations
[Improvements by priority]

## Detailed Analysis

### Architecture & API Design
[Findings from the design and interface pass]

### Implementation Quality
[Findings from the implementation pass]

### Testing & Security
[Findings from the test and security pass]

## Visual Evidence
["N/A — no frontend impact", or "Not captured: <reason>", or
"Attached in follow-up comment below" — screenshots go via
`gh pr comment --attach`, never as branch files or raw links]

## Final Recommendation
[Approve / Approve with Conditions / Request Changes with reasoning]
EOF
)"
```

Be thorough but focus on the most impactful issues. Every finding needs a `file:line` reference and a concrete suggested fix.

If a review has already been posted on this PR, do not write another full review. Post an update that states what changed since the last review, whether each previous finding is resolved, and the current `Final Recommendation`. Repeat unchanged findings only when their status changed.

Use `gh pr review <n> --approve` only for an approval. Do not use a formal review for change requests; use `gh pr comment` as shown above.

Frontend rule: if the changes touch the frontend directly or indirectly (web code, API shapes the UI consumes, emails the UI triggers), obtain visual evidence with screenshots and review the visual changes. Follow `.agents/browser.md` for the harness, the seeded account, and how to capture a screenshot that proves the flow ran. If screenshots contradict the PR description, or if the required visual evidence cannot be obtained, apply `needs-human`, remove `in-progress`, and STOP:

```bash
gh pr edit <n> --add-label needs-human
gh pr edit <n> --remove-label in-progress
```

No visual evidence → no approval on frontend-touching PRs. Attach the screenshot to the PR comment too.

## 5. Fix all major issues, report, STOP

Check out the PR branch, fix every major finding, then run the repo quality gate (resolve from README / AGENTS.md / Makefile / CI workflows — at minimum lint, tests, and a build of every area touched).

If a fix itself needs review (non-trivial), re-review the changed hunks before proceeding. Commit and push the fixes onto the PR branch before commenting — the PR must show the new commits:

```bash
git add -A && git commit -m "<type(scope): summary>" && git push
```

Then report what was fixed, using the same section structure as the review comment so the next agent reads one consistent shape:

```bash
gh pr comment <n> --body "$(cat <<'EOF'
# PR #<n> Review Update

## Overview
[What this iteration changed since the last review]

## Key Findings

### Strengths
[What is now in good shape]

### Critical Issues
[Still-unresolved blockers, or "None"]

### Recommendations
[Remaining improvements by priority]

## Detailed Analysis

### Architecture & API Design
[What the fixes changed, or "Unchanged"]

### Implementation Quality
[What the fixes changed, or "Unchanged"]

### Testing & Security
[What the fixes changed, or "Unchanged"]

## Visual Evidence
[What was re-captured, or "Unchanged"]

## Final Recommendation
[Request Changes, if blockers remain — otherwise state what the next
session must confirm before it may merge]
EOF
)"
```

Never write a second full review when one already exists — this is an update, as described in step 4.

Before STOP, release the claim:

```bash
gh pr edit <n> --remove-label in-progress
```

Then STOP. Do not merge in this iteration — the next fresh session re-reviews from step 1.

## 6. Escalation

If at any point the PR cannot move forward on its own (unresolvable conflicts, failing checks with no clear cause, scope questions, author decisions needed):

```bash
gh pr edit <n> --add-label needs-human
gh pr edit <n> --remove-label in-progress
```

Then STOP and report why.

## 7. Approval path: file minors, then merge and close

Only when a review (yours or adopted) approves with all majors complete, and only for non-high-risk PRs (step 3):

1. Create one issue per deferred finding (title, repro/context, `enhancement` label). Reference the PR number in each body.
2. Apply `agent:done` before merging, so a concurrent step-1 run cannot claim the PR mid-merge. This label also survives the merge and keeps the PR out of every later run.
3. Merge and close:

```bash
gh pr edit <n> --add-label agent:done
gh pr merge <n> --squash
gh pr edit <n> --remove-label in-progress
```

Report the merge plus the created issue numbers.

## 8. Commit and push before finishing (MANDATORY)

This overrides the `AGENTS.md` no-commit default: the agent MUST commit and push all work before finishing the session — fixes onto the PR branch, anything else onto the working branch. Never leave work uncommitted or unpushed. Verify with `git status -sb` (clean) and `gh pr view <n>` (new commits visible). Before reporting done, verify that `in-progress` is absent from the PR.
