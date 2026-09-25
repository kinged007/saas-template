# Review-PR workflow

Pick up the next open PR, review it, and either fix-and-stop or merge-and-close. Fix majors and minors, report, STOP — the next fresh session re-reviews. You can only merge and close a PR if all issues were fixed in a previous session. You cannot review, fix, and close in one session — if you fix issues in your session, hand off for a new review session to review and close. Run from the repo root. All `gh` commands assume the repo default (current directory) — never hardcode `repos/<owner>/<repo>`.

There is no `backlog` label. The review labels are `review-in-progress` (claimed for review), `needs-human` (blocked, needs the owner), and `agent:done` (reviewed, ready to merge or merged).

## Process lifecycle and cleanup (MANDATORY)

Never finish a run with a process started by the agent still running. This includes the API/frontend stack, supervisors, watchers, test servers, `obscura serve`, and CDP clients. Stop every owned process on success, failure, cancellation, timeout, and every early `STOP` path. A timeout is only a safety net, not cleanup.

Run long-lived commands in the foreground when possible. If backgrounding is necessary, give the command a finite budget and record its PID. For example, on Linux:

```bash
timeout --signal=TERM --kill-after=15s 1h <command>
```

`obscura serve` has no built-in duration option, so use a one-hour cap and a session-specific storage directory:

```bash
timeout --signal=TERM --kill-after=15s 1h \
  obscura serve --allow-private-network --storage-dir <session-dir>
```

Use a task-appropriate cap for the application stack as well. At cleanup, send `SIGTERM` to the exact supervisor or process you started, wait for it, then use `SIGKILL` only if it remains alive. Verify its children and the ports it owns. Never kill an unknown process or clear a port you did not open. Remove temporary PID/log/browser files. If cleanup cannot be verified, do not report completion.

## 0. Dev environment and seeded credentials (read first)

Start the stack with the repo's own dev command (see README / AGENTS.md / Makefile — never leave it running orphaned). The dev command usually installs deps, migrates, and seeds automatically.

Discover the seeded credentials yourself — they show in the dev startup output and live in the repo's seed script/fixtures.

Log in with a seeded account for manual/visual verification (including Obscura screenshots in step 4). If the task needs a different user shape, seed one following the repo's seed patterns or register through the UI — do not hardcode ad-hoc credentials in the codebase.

Browser: Obscura only. Any browser use MUST be Obscura — never standalone Playwright or chrome-devtools (playwright-core is allowed only as a CDP client driving `obscura serve`). If `obscura` is not installed, install it from https://github.com/h4ckf0r0day/obscura. Always pass `--allow-private-network` (loopback is blocked without it). Use the `localhost` URL of the dev frontend, never its `127.0.0.1` equivalent — login can break on 127.x (dev CORS default, not a product bug; do not file it). For login-gated screenshots: `obscura serve --allow-private-network --storage-dir <dir>`, connect over CDP (`chromium.connectOverCDP`, install `playwright-core` if needed), fill the login form's email/password fields via pressSequentially, click submit — one-shot `obscura fetch -e` cannot do multi-step login. Screenshots MUST be taken logged in with a seeded account. Review each screenshot yourself; if it does not show the intended page, retry until it does. A login-screen screenshot when a logged-in page was intended is not acceptable.

## 1. Find the next open PR

Skip any PR labelled `wontfix`, `needs-human`, `in-progress`, `review-in-progress`, `invalid`, `duplicate`, or `agent:done` — never touch those, even if open:

```bash
gh pr list --state open --limit 50 \
  --json number,title,labels \
  -q '.[] | select(([.labels[].name] | inside(["wontfix","needs-human","in-progress","review-in-progress","invalid","duplicate","agent:done"]) | not)) | "\(.number) | \(.title)"'
```

Take the first listed. If the list is empty, stop and report that no actionable PR exists. Otherwise claim it:

```bash
gh pr edit <n> --add-label review-in-progress
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

Treat the newest review/comment as authoritative where things conflict. If anything in the thread is ambiguous or the PR is conflicted beyond a trivial rebase, apply `needs-human` and STOP:

```bash
gh pr edit <n> --add-label needs-human
```

## 3. Classify risk

A PR is **high-risk** if it touches any of:

- files owned in `.github/CODEOWNERS` (high-impact files, migrations, infra)
- auth, sessions, tokens, passwords, OAuth flows
- credential storage, encryption, secrets handling
- production config, ports, deployment (`infra/`, Docker, env templates)

High-risk PRs follow the same review-and-fix path below, but the agent must NEVER merge them. After review/fixes, apply `needs-human` for the merge decision and STOP. Only the owner merges high-risk work.

## 4. Review, unless a recent review already stands

If a review was submitted since the last code change (compare review `submittedAt` against the latest commit date), adopt its verdict instead of re-reviewing: majors already listed → go to step 5; approved → go to step 7 (or stop with `needs-human` if high-risk per step 3).

Otherwise review thoroughly against:

- the repo's architecture docs plus related `docs/`; the project's context map / wiki if present, then the actual source files; check blast radius before touching widely-imported files.
- Correctness, tests, error handling, security, migration safety. Classify every finding as **major** (blocks merge: bugs, data loss, security, broken tests, arch violations) or **minor/deferred** (nits, follow-ups, polish).

Post the review as a PR review (approve / request-changes / comment accordingly):

```bash
gh pr review <n> --request-changes --body "..."  # or --approve / --comment
```

Frontend rule: if the changes touch the frontend directly or indirectly (web code, API shapes the UI consumes, emails the UI triggers), obtain visual evidence with screenshots and review the visual changes. Use Obscura per §0 (`obscura fetch --allow-private-network <url> -s shot.png` for public pages; `serve` + CDP login flow for login-gated pages) against the running dev stack at its `localhost` frontend URL, logged in with a seeded account. Review each screenshot yourself and retry on a wrong capture — a login-screen shot for a logged-in page is not acceptable. If screenshots contradict the PR description, apply `needs-human` and STOP. No visual evidence → no approval on frontend-touching PRs. Attach the screenshot to the PR comment too.

## 5. Fix all major issues, report, STOP

Check out the PR branch, fix every major finding, then run the repo quality gate (resolve from README / AGENTS.md / Makefile / CI workflows — at minimum lint, tests, and a build of every area touched).

If a fix itself needs review (non-trivial), re-review the changed hunks before proceeding. Commit and push the fixes onto the PR branch before commenting — the PR must show the new commits:

```bash
git add -A && git commit -m "<type(scope): summary>" && git push
```

Then report what was fixed:

```bash
gh pr comment <n> --body "## Fixes this iteration
- ...
## Still open / deferred
- ..."
```

Then STOP. Do not merge in this iteration — the next fresh session re-reviews from step 1.

## 6. Escalation

If at any point the PR cannot move forward on its own (unresolvable conflicts, failing checks with no clear cause, scope questions, author decisions needed):

```bash
gh pr edit <n> --add-label needs-human
```

Then STOP and report why.

## 7. Approval path: file minors, then merge and close

Only when a review (yours or adopted) approves with all majors complete, and only for non-high-risk PRs (step 3):

1. Create one issue per deferred finding (title, repro/context, `enhancement` label). Reference the PR number in each body.
2. Merge and close:

```bash
gh pr merge <n> --merge
gh pr edit <n> --remove-label review-in-progress  # if set
```

Report the merge plus the created issue numbers.

## 8. Commit and push before finishing (MANDATORY)

This overrides the `AGENTS.md` no-commit default: the agent MUST commit and push all work before finishing the session — fixes onto the PR branch, anything else onto the working branch. Never leave work uncommitted or unpushed. Verify with `git status -sb` (clean) and `gh pr view <n>` (new commits visible) before reporting done.
