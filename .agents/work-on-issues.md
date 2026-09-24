# Next-issue workflow

Pick up the next actionable piece of work and implement it. Run from the repo root. All `gh` commands assume the repo default (current directory) — never hardcode `repos/<owner>/<repo>`.

This repo currently has zero milestones. There is no milestone ordering. Work directly from the open-issue list. If milestones are added later, process the lowest-numbered open milestone first, skipping staging/empty tracks unless told otherwise.

## 1. List open issues

```bash
gh issue list --state open --limit 50 \
  --json number,title,labels \
  -q '.[] | "\(.number) | \(.title) | \([.labels[].name] | join(","))"'
```

## 2. Drop finished, invalid, or claimed issues

Skip any issue labelled `wontfix`, `needs-human`, `in-progress`, `review-in-progress`, `invalid`, `duplicate`, or `agent:done` — never touch those, even if open. There is no `backlog` label. The listing query excludes them deterministically:

```bash
gh issue list --state open --limit 50 \
  --json number,title,labels \
  -q '.[] | select(([.labels[].name] | inside(["wontfix","needs-human","in-progress","review-in-progress","invalid","duplicate","agent:done"]) | not)) | "\(.number) | \(.title)"'
```

If `gh`'s `--jq`/`-q` dialect rejects `inside`, fall back to filtering client-side (fetch `--json number,title,labels` and drop any issue whose label set intersects the skip set above).

## 3. Find the next unblocked and related open issues

If a candidate carries the `agent:plan` label, post a brief issue comment saying planning is still pending and stop without making changes (the label was added after dispatch). Do not implement it.

For each remaining candidate in listed order, check blockers:

```bash
gh issue view <n> --json blockedBy \
  -q '.blockedBy.nodes[] | "\(.number) \(.state) \(.title)"'
```

Take issues with no blocker in `OPEN` state, that are related or similar to each other. Take on no more than 5 minor issues at a time. The more complex the issue, the fewer to claim at the same time. Only claim issues that are related or similar, otherwise just claim ONE issue.
If every open issue is blocked by another open issue, stop and report that the backlog is drained or deadlocked.

## 4. Read the issue threads first, then plan, then post the plan

Read ALL existing comments on the issues BEFORE planning — some issues already carry a plan or steering notes that override the body:

```bash
gh issue view <n> --json title,body,comments,labels \
  -q '.title, .body, (.comments[] | "--- @\(.author.login) \(.createdAt) ---\n\(.body)")'
```

Treat comments as authoritative over the body where they conflict (newest wins). Comments may contain corrections, reproduction details, or scope changes that override the description. If an approved plan was posted, follow it. If a comment already contains a plan, adopt it unless the codebase has moved on, and say so in the posted plan.

If the task is already resolved, post an issue comment saying so and stop without making changes.

Context to read:

- the repo's architecture docs; check `docs/` for related docs on the area being touched.
- the project's context map / wiki if present, then the source files it lists. Never plan from the wiki alone.
- check blast radius before touching widely-imported files.
- Follow the repo's own instructions (tooling, make targets, no new dependencies without asking).
- Post the plan as an issue comment before writing code:

```bash
gh issue comment <n> --body "## Plan
...
### Related issues
...
### Files to touch
...
### Acceptance (from issue)
..."
```

If the plan is straightforward and follows existing code structure and architecture patterns, proceed with auto-approval. If the plan contains architectural changes or a significant shift in design, request human approval. Apply the label `needs-human`, then STOP. Do not proceed.

```bash
gh issue edit <n> --add-label needs-human
```

## 0. Dev environment and seeded credentials (read first)

Start the stack with the repo's own dev command (see README / AGENTS.md / Makefile — never leave it running orphaned). The dev command usually installs deps, migrates, and seeds automatically.

Discover the seeded credentials yourself — they show in the dev startup output and live in the repo's seed script/fixtures.

Log in with a seeded account for manual/visual verification. If the task needs a different user shape, seed one following the repo's seed patterns or register through the UI — do not hardcode ad-hoc credentials in the codebase.

Browser: Obscura only. Any browser use MUST be Obscura — never standalone Playwright or chrome-devtools (playwright-core is allowed only as a CDP client driving `obscura serve`). If `obscura` is not installed, install it from https://github.com/h4ckf0r0day/obscura. Always pass `--allow-private-network` (loopback is blocked without it). Use the `localhost` URL of the dev frontend, never its `127.0.0.1` equivalent — login can break on 127.x (dev CORS default, not a product bug; do not file it). For login-gated screenshots: `obscura serve --allow-private-network --storage-dir <dir>`, connect over CDP (`chromium.connectOverCDP`, install `playwright-core` if needed), fill the login form's email/password fields via pressSequentially, click submit — one-shot `obscura fetch -e` cannot do multi-step login. Screenshots MUST be taken logged in with a seeded account. Review each screenshot yourself; if it does not show the intended page, retry until it does. A login-screen screenshot when a logged-in page was intended is not acceptable.

## 5. Mark in-progress, then implement

```bash
gh issue edit <n> --add-label in-progress
```

Implement the posted plan, then run the repo quality gate (resolve from README / AGENTS.md / Makefile / CI workflows — at minimum lint, tests, and a build of every area touched).

Review your own diff (`git diff`) for correctness, regressions, and convention compliance before finishing.

## 5b. Pre-PR testing gate (MANDATORY)

Before opening the PR, the agent MUST prove the change does not break the pipeline. If CI workflows exist (`.github/workflows/`), read them and manually run every check they run (lint, typecheck, tests, build) before submitting. If no CI exists, run the repo's full quality gate instead (see README / AGENTS.md — at minimum lint, tests, and a build of every area touched) and make sure all tests pass.

Do not open the PR while any of these fail. If a check fails, fix the cause (not the check) and re-run until green. Never submit a PR with a red gate and a promise to fix it after — the next session starts from pushed state, so a broken push poisons every session after it. If a check cannot be made green for reasons outside the change, document the failure in the PR body under Verification and apply the `needs-human` label instead of submitting.

If the plan proves wrong mid-implementation, update the issue comment with what changed and why.

If implementation and testing succeed, submit a PR for the issue (push the branch first, see §6). Explain in detail what the problem was, what was implemented, and how correctness was verified.

## 7. Open the pull request

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

## 8. Post the closing issue comment

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

## 6. Commit and push before finishing (MANDATORY)

This overrides the `AGENTS.md` no-commit default: the agent MUST commit and push all work (code, tests, and the issue/PR comments are already remote) before finishing the session. Never leave work uncommitted or unpushed — the next session starts from the pushed state.

```bash
git add -A && git commit -m "<type(scope): summary>" && git push
# PR fixes: commit onto the PR branch and push so the PR updates
git push -u origin $(git branch --show-current)
```

Verify the push landed (`git status -sb` shows clean, `gh pr view <n>` shows the new commits) before reporting done.
