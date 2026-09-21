# Next-PR workflow

Pick up the next open PR, review it, and either fix-and-stop or merge-and-close. One iteration per session: fix majors, report, STOP — the next fresh session re-reviews. Run from the repo root. All `gh` commands assume the repo default (current directory).

## 0. Dev environment and seeded credentials (read first)

Start the stack with `make dev` (API on :8000, web on :5173 — Ctrl-C stops both; never leave it running orphaned). `make dev` migrates and seeds automatically. The seed (`apps/api/src/seed.py`, `make api-seed` to re-run) creates demo users all sharing password `password`: `admin@example.com`, `user1@example.com`, `user2@example.com`, with workspaces `acme-corp` and `globex`, memberships, and pending invitations.

Log in with a seeded account for manual/visual verification (including Obscura screenshots in step 3). If the task needs a different user shape, seed a new one via `seed.py` patterns or register through the UI — do not hardcode ad-hoc credentials in the codebase.

## 1. Find the next open PR

Skip any PR labelled `wontfix`, `backlog`, or `needs-human` — never touch those, even if open:

```bash
gh pr list --state open --limit 50 \
  --search "-label:backlog -label:wontfix -label:needs-human" \
  --json number,title --jq '.[] | "\(.number) | \(.title)"'
```

Take the first listed. If the list is empty, stop and report that no actionable PR exists.

## 2. Read the PR thread first

Read the body, ALL comments, and ALL reviews BEFORE doing anything else — prior review verdicts and steering notes override a cold read:

```bash
gh pr view <n> --json title,body,comments,reviews,labels,mergeable,mergeStateStatus \
  -q '.title, .body, (.comments[] | "--- @\(.author.login) \(.createdAt) ---\n\(.body)"), (.reviews[] | "--- REVIEW @\(.author.login) \(.state) \(.submittedAt) ---\n\(.body)")'
```

Also fetch the diff:

```bash
gh pr diff <n> --patch  # full diff into context only if small; otherwise summarise per-file
```

Treat the newest review/comment as authoritative where things conflict. If anything in the thread is ambiguous or the PR is conflicted beyond a trivial rebase, apply `needs-human` and STOP:

```bash
gh pr edit <n> --add-label needs-human
```

## 3. Review, unless a recent review already stands

If a review was submitted since the last code change (compare review `submittedAt` against the latest commit date), adopt its verdict instead of re-reviewing: majors already listed → go to step 4; approved → go to step 6.

Otherwise review thoroughly against:

- `docs/ARCHITECTURE.md` plus related `docs/`; `.codesight/wiki/` domain article then the actual source files; `.codesight/graph.md` blast radius for high-impact files.
- Correctness, tests, error handling, security, migration safety. Classify every finding as **major** (blocks merge: bugs, data loss, security, broken tests, arch violations) or **minor/deferred** (nits, follow-ups, polish).

Post the review as a PR review (approve / request-changes / comment accordingly):

```bash
gh pr review <n> --request-changes --body "..."  # or --approve / --comment
```

Frontend rule: if the changes touch the frontend directly or indirectly (web code, API shapes the UI consumes, emails the UI triggers), obtain visual evidence with screenshots and review the visual changes. Use Obscura (`obscura fetch --allow-private-network <url> -s shot.png`, `obscura serve --allow-private-network` for JS-rendered flows) against a running dev stack (`make dev`). No visual evidence → no approval on frontend-touching PRs. Make sure you attach the screenshot into the PR comment too.

## 4. Fix all major issues, report, STOP

Check out the PR branch, fix every major finding, run the repo quality gate (`make api-lint`, relevant `pytest`, `npm run build` for web changes). If a fix itself needs review (non-trivial), re-review the changed hunks before proceeding. Commit and push the fixes onto the PR branch before commenting — the PR must show the new commits:

Comment what was fixed:

```bash
git add -A && git commit -m "<type(scope): summary>" && git push
```

Then comment what was fixed:

```bash
gh pr comment <n> --body "## Fixes this iteration
- ...
## Still open / deferred
- ..."
```

Then STOP. Do not merge in this iteration — the next fresh session re-reviews from step 1.

## 7. Commit and push before finishing (MANDATORY)

This overrides the `AGENTS.md` no-commit default: the agent MUST commit and push all work before finishing the session — fixes onto the PR branch, anything else onto the working branch. Never leave work uncommitted or unpushed. Verify with `git status -sb` (clean) and `gh pr view <n>` (new commits visible) before reporting done.

## 5. Escalation

If at any point the PR cannot move forward on its own (unresolvable conflicts, failing checks with no clear cause, scope questions, author decisions needed):

```bash
gh pr edit <n> --add-label needs-human
```

Then STOP and report why.

## 6. Approval path: file minors, then merge and close

Only when a review (yours or adopted) approves with all majors complete:

1. Create one issue per minor/deferred finding (title, repro/context, `enhancement` label, milestone of the area if one fits). Reference the PR number in each body.
2. Merge and close:

```bash
gh pr merge <n> --merge
gh pr edit <n> --remove-label in-progress  # if set
```

Report the merge plus the created issue numbers.
