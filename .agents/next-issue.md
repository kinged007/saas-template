# Next-issue workflow

Pick up the next actionable piece of template work and implement it. Run from the repo root. All `gh` commands assume the repo default (current directory).

## 1. List all milestones

```bash
gh api repos/kinged007/saas-template/milestones --paginate \
  -q '.[] | "\(.number) | \(.title) | open:\(.open_issues) closed:\(.closed_issues)"'
```

Known milestones (numbered prefix = implementation order):

| # | Milestone | Why this order |
|---|-----------|----------------|
| 4 | 01 - Messaging & Notifications | Email infra unlocks recovery, digests, invites |
| 3 | 02 - Auth & Account Security | Recovery/OIDC once email exists |
| 5 | 03 - Workspaces & Members | Lifecycle on top of auth + email |
| 6 | 04 - Data & Files | Storage + search after identity settles |
| 7 | 05 - Ops & Admin | Operate once there are users |
| 8 | 06 - Developer Experience | Versioning/quotas last, API must stabilize first |
| 1 | Agent Platform | Separate track, not part of this ordering |
| 2 | Core Features | Empty staging milestone — always skip |

## 2. Drop finished or empty milestones

Keep only milestones with `open > 0`. Skip `Core Features` (staging, permanently empty) and `Agent Platform` (separate track) unless the user says otherwise. Process the rest lowest-numbered first.

## 3. Find the next unblocked open issue in the milestone

Skip any issue labelled `wontfix` or `backlog` or `needs-human` or `in-progress` — never touch those, even if open. The listing query excludes them deterministically:

```bash
MS="<milestone title>"
gh issue list --milestone "$MS" --state open --limit 50 \
  --json number,title,labels \
  -q '.[] | select(([.labels[].name] | inside(["wontfix","backlog","needs-human","in-progress"]) | not)) | "\(.number) | \(.title)"'
```

If `gh`'s `--jq`/`-q` dialect rejects `inside`, fall back to filtering client-side (fetch `--json number,title,labels` and drop any issue whose label set intersects `wontfix`/`backlog`/`needs-human`/`in-progress`).

For each remaining candidate in listed order, check blockers:

```bash
gh issue view <n> --json blockedBy \
  -q '.blockedBy.nodes[] | "\(.number) \(.state) \(.title)"'
```

Take the first issue with no blocker in `OPEN` state. If every open issue is blocked by another open issue, move to the next milestone. If no milestone yields an issue, stop and report that the backlog is drained or deadlocked.

## 4. Read the issue thread first, then plan, then post the plan

Read ALL existing comments on the issue BEFORE planning — some issues already carry a plan or steering notes that override the body:

```bash
gh issue view <n> --json title,body,comments,labels \
  -q '.title, .body, (.comments[] | "--- @\(.author.login) \(.createdAt) ---\n\(.body)")'
```

Treat comments as authoritative over the body where they conflict (newest wins); if a comment already contains a plan, adopt it unless the codebase has moved on, and say so in your posted plan.

Context to read:

- `docs/ARCHITECTURE.md` for system design and conventions; check `docs/` for related docs (providers, setup) on the area you are touching.
- `.codesight/wiki/index.md`, then `overview.md`, then the domain article for the area, then the source files it lists. Never plan from the wiki alone.
- Check `.codesight/graph.md` for blast radius before touching high-impact files.
- Follow `AGENTS.md` (repo tooling, make targets, no new dependencies without asking).
- Post the plan as an issue comment before writing code:

```bash
gh issue comment <n> --body "## Plan
...
### Files to touch
...
### Acceptance (from issue)
..."
```

If the plan is pretty straight forward, meets the code structure and architecture design patterns, then you may proceed with auto-approval. If the plan contains architectural changes, or significant changes or shift in design, then you need to request a human approval. Apply the label 'needs-human' for this, then STOP. Do not procced!

```bash
gh issue edit <n> --add-label needs-human
```

## 0. Dev environment and seeded credentials (read first)

Start the stack with `make dev` (API on :8000, web on :5173 — Ctrl-C stops both; never leave it running orphaned). `make dev` migrates and seeds automatically. The seed (`apps/api/src/seed.py`, `make api-seed` to re-run) creates demo users all sharing password `password`: `admin@example.com`, `user1@example.com`, `user2@example.com`, with workspaces `acme-corp` and `globex`, memberships, and pending invitations.

Log in with a seeded account for manual/visual verification. If the task needs a different user shape, seed a new one via `seed.py` patterns or register through the UI — do not hardcode ad-hoc credentials in the codebase.

## 5. Mark in-progress, then implement

```bash
gh issue edit <n> --add-label in-progress
```

Implement the posted plan, then run the repo quality gate (`make api-lint`, relevant `pytest`, `npm run build` for web changes). If the plan proves wrong mid-implementation, update the issue comment with what changed and why.

If the implementation and testing is successful, then please submit a PR for this issue. Explain in detail what the problem was and what you implemented, and how you verified it was correct.

## 6. Commit and push before finishing (MANDATORY)

This overrides the `AGENTS.md` no-commit default: the agent MUST commit and push all work (code, tests, and the issue/PR comments are already remote) before finishing the session. Never leave work uncommitted or unpushed — the next session starts from the pushed state.

```bash
git add -A && git commit -m "<type(scope): summary>" && git push
# PR fixes: commit onto the PR branch and push so the PR updates
git push -u origin $(git branch --show-current)
```

Verify the push landed (`git status -sb` shows clean, `gh pr view <n>` shows the new commits) before reporting done.
