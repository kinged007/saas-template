# Fleet label contract

Single source for the `agent:*` vocabulary: what state each label means, what sets
it, and what reads it. Read this before adding, removing, or renaming an
`agent:*` label anywhere (`.agents/` prose, label descriptions, dispatcher
config): `make label-contract` fails when the two drift apart.

Three consumers act on these labels from inside this repository:

- `.agents/work-on-issues.md` and `.agents/review_pr.md` — the issue and
  review-agent workflows. They read labels and write the claim labels,
  `agent:done`, and (on approval) `agent:merge`.
- `scripts/merge_queue.py`, run by `.github/workflows/merge-queue.yml` — the
  merge queue. It is the only thing that merges into `dev`; it selects on
  `agent:merge` and applies the follow-up labels below when a check fails.
- `.github/workflows/branch-guard.yml` — opens a `needs-human` issue when a push
  breaks the branch model.

Everything else named in "Read by" is operator config (`WORKFLOW.*.md` on the
fleet host) and is not in this repository, so a loop name can only be checked
there, never here. "Operator" in "Set by" means a person, or the product loop
acting for one — no agent in this repository applies those labels.

How to verify a row: `gh label list --limit 200` shows the descriptions;
`grep -rn 'agent:' .agents/` shows the in-repo references; `make label-contract`
runs the same two rules CI runs. Rows cite a file, not a line number: a line
number goes stale on the next edit, and the check compares files.

## Consumed labels

| Label | Kind | State / meaning | Set by | Read by |
| --- | --- | --- | --- | --- |
| `agent:triage` | Trigger, issues | Classify, de-duplicate and route the issue | Operator | Fleet issues-light loop |
| `agent:groom` | Trigger, issues | Backlog pass for duplicates and stale issues | Operator | Fleet issues-light loop |
| `agent:build` | Trigger, issues | Implement the issue and open a PR | Operator | Fleet issues-builder loop |
| `agent:docs` | Trigger, issues | Update docs and area files for merged changes | Operator | Fleet issues-builder loop |
| `agent:spec` | Trigger, issues | Write the spec, then plan | Operator | Fleet issues-planner loop |
| `agent:plan` | Trigger, issues | Write the plan, tasks and checklist | Operator | Fleet issues-planner loop; `.agents/work-on-issues.md` stops on a candidate that carries it and posts "planning pending" |
| `agent:plan-check` | Trigger, issues | Second-model review of spec and plan | Operator | Fleet issues-reviewer loop |
| `agent:split` | Trigger, issues | Break an epic into child issues | Operator | Fleet issues-planner loop |
| `agent:research` | Trigger, issues | Explore code and sources to answer the issue | Operator | Fleet issues-planner loop |
| `agent:retro` | Trigger, issues | Analyse failed runs, propose prompt changes | Operator | Fleet issues-planner loop |
| `agent:area-map` | Trigger, issues | Write or refresh the `.agents/areas/` files | Operator | Fleet issues-planner loop. No `.agents/areas/` directory exists in this repository yet |
| `agent:review` | Trigger, PRs | Needs a verdict at the current head | Operator; the merge queue when it runs with `--enforce-approval` | Fleet prs-reviewer loop. `.agents/work-on-issues.md` names it only to forbid a build agent from applying it, so a person starts the review |
| `agent:merge` | Trigger, PRs | Approved and waiting in the merge queue | Review agent on approval | `scripts/merge_queue.py`, both to select and to remove it when a check fails |
| `agent:revise` | Trigger, PRs | The base is not `dev`, or the `Area:` line is missing or invalid | Merge queue | `scripts/merge_queue.py` (checks 2 and 6); Fleet prs-builder loop |
| `agent:ci-fix` | Trigger, PRs | A PR check is red, or a merged slice was reverted for a red `dev` | Merge queue | `scripts/merge_queue.py` (check 4, red-dev revert); Fleet prs-builder loop |
| `agent:rebase` | Trigger, PRs | Textual conflict with the integration branch | Merge queue | `scripts/merge_queue.py` (check 3); Fleet prs-builder loop |
| `agent:verify` | Trigger, PRs | Run checks and acceptance-criteria coverage | Operator | Fleet prs-light loop. Nothing here acts on it: the single in-repo mention is a historical spec record |
| `agent:done` | State, issues and PRs | Finished and out of every dispatch query | `.agents/work-on-issues.md` step 10 (issues); the review agent on its approval and high-risk paths (PRs) | The two dispatch queries in `.agents/work-on-issues.md` and `.agents/review_pr.md` |

`agent:done` on PRs is a live inconsistency: `.agents/review_pr.md` still
applies it, while `docs/architecture/CI-CD.md` §5 states it is no longer used on
open PRs and that `agent:merge` replaces it. The effect is harmless — a PR
carrying it drops out of the review dispatch query, which is what the label
means anyway — but the two files disagree, and which one is authoritative is
the maintainer's call.

`docs/architecture/CI-CD.md` §5 describes the same PR labels as a state machine
("exactly one `agent:*` trigger label at a time"). Where the two files disagree,
the code wins: `scripts/merge_queue.py` for what the queue sets, `.agents/` for
what an agent sets. That table is not covered by `make label-contract`, which
reads `.agents/` only.

Claim and escalation labels are not `agent:*`-prefixed but belong to the same
contract:

| Label | Meaning |
| --- | --- |
| `in-progress` | Claim lock, taken by a workflow before it starts and released on every exit path |
| `review-in-progress` | Also treated as claimed. The label does not exist in the repository's label set (`gh label list` does not show it); the dispatch filters keep it so a PR claimed under an older setup is not picked up twice |
| `needs-human` | Blocked; a person has to act. Skips both dispatch queries |
| `backlog` | Deferred by a person. Skips both dispatch queries; never dispatched |
| `wontfix`, `invalid`, `duplicate` | Closed or not actionable. Both dispatch queries skip them; the workflows only ever read them |

Those seven labels plus `agent:done` are the skip list both workflows hardcode
(`.agents/work-on-issues.md` step 1, `.agents/review_pr.md` step 1). A label
added to one query and not the other re-opens the gap the contract exists to
close.

## Operator actions

Only `scripts/merge_queue.py` merges into `dev`, and only the maintainer merges
into `main` — and only from `staging`, through a promotion PR
(`docs/architecture/CI-CD.md` §4). Do not merge a PR by hand into any branch.
The promotion workflow (`promote.yml`) is not in this repository yet; the rule
holds either way.

The merge queue applies `agent:rebase`, `agent:ci-fix` and `agent:revise`
itself when a check fails, and removes `agent:merge` at the same time; it
applies `agent:review` only for check 5, and only when it runs with
`--enforce-approval` (the workflow does not pass it, so check 5 is advisory
today). A person only does the work when no loop picks the label up, and
removes the label once done so the loop never double-acts:

- Needs rebase: merge the base into the PR branch (never rebase, never
  force-push), resolve conflicts keeping both sides' intent, run the quality
  gate, push. Then remove `agent:rebase`.
- Needs a fix (red checks): fix the cause, run the quality gate, push. Then
  remove `agent:ci-fix`.
- Needs changes after review: apply the review findings, run the quality gate,
  push. Then remove `agent:revise`.

Nothing in this repository applies `agent:revise` after a review:
`.agents/review_pr.md` fixes majors in the same session and never sets it, and
the merge queue sets it only for a wrong base or a bad `Area:` line. So on a PR
with review findings the label comes from the external Fleet prs-builder loop,
or from nobody — treat its absence as normal and check the PR thread, not the
label, to decide whether work is outstanding.

To get a PR merged: it needs `agent:merge` and the merge-queue checks — `dev` CI
green, base `dev`, no conflict, every check green at the head, a review event
approving that head SHA (advisory in Stage 1), and an `Area:` line in the body.
A review approves by applying `agent:merge` (`.agents/review_pr.md` step 7).
Never apply `agent:merge` to a PR the review agent has not approved.

High-risk PRs are never queued: the review agent withholds `agent:merge` and
applies `needs-human` instead. The merge queue does not read `risk:high`, so
that withheld label is the only thing keeping such a PR out of the queue. Only
the owner merges high-risk work.

## Labels that start no work

`agent:plan-build` starts no agent: no loop references it, and no file in this
repository does either. Do not apply a trigger label to start work outside its
loop, and clear the label once a person has done the work by hand. Open PRs
still carry `agent:build`, which is an issue-side trigger no PR query reads —
clearing it changes nothing, and it is not a reason to re-dispatch the PR.

## Labels outside this contract

Nothing in this repository reads these; they are for people and the product
loop, and listing them here is what stops them being mistaken for triggers:

- `P0`, `P1`, `P2` are ranked by the issues query in
  `.agents/work-on-issues.md`, and `P0` also jumps the merge queue. `P3` is
  ranked by neither — the issues query orders `P0`, `P1`, `P2`, then everything
  else by age.
- `risk:low`, `risk:high`, `track:*`, `type:*`, `size:*`, `area:*`,
  `needs-triage`, `united-into`, `blocked`, `auto`: classification a person or
  the product loop writes. Nothing here reads them. `.agents/review_pr.md`
  step 3 derives high-risk from the paths a PR touches, not from `risk:high`,
  so that label records a decision rather than causing one.
- `blocked` is worth calling out because its description claims behaviour that
  does not exist: "waits for the issues it depends on; merge removes it". No
  merge queue step in `scripts/merge_queue.py` removes it, and
  `.agents/work-on-issues.md` reads GitHub's issue dependencies (`blockedBy`),
  not the label. A `blocked` issue is still dispatched, so apply `backlog` or
  `needs-human` instead when an issue must not be picked up.
- The GitHub default set (`bug`, `documentation`, `enhancement`, `good first
  issue`, `help wanted`, `question`, `accessibility`, `docs`) is for people.

`area:*` does not match the `Area:` trailer. The four values the merge queue
accepts are `api`, `web`, `db` and `infra`; the `area:*` label descriptions
("cmd/jig commands", "supervisor, gate and service", "dashboard, collector and
API") name the fleet's own CLI, which is not this repository. Nothing here reads
either form.
