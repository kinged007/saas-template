# Fleet label contract

Single source for every `agent:*` label: what state it means and what consumes
it. Read this before adding, removing, or renaming an `agent:*` label anywhere
(`.agents/` prose, label descriptions, dispatcher configs): `make label-contract`
fails when the two drift apart.

How to verify a row: `gh label list --limit 100` shows the descriptions;
`grep -rn 'agent:' .agents/` shows the in-repo references; the fleet loops named
below are operator config (`WORKFLOW.*.md` on the fleet host) and are not
versioned in this repository.

## Consumed labels

| Label | Kind | State / meaning | Consumed by |
| --- | --- | --- | --- |
| `agent:triage` | Trigger, issues | Classify, de-duplicate and route the issue | Fleet issues-light loop |
| `agent:groom` | Trigger, issues | Backlog pass for duplicates and stale issues | Fleet issues-light loop |
| `agent:build` | Trigger, issues | Implement the issue and open a PR | Fleet issues-builder loop |
| `agent:docs` | Trigger, issues | Update docs and area files for merged changes | Fleet issues-builder loop |
| `agent:spec` | Trigger, issues | Write the spec, then plan | Fleet issues-planner loop |
| `agent:plan` | Trigger, issues | Write the plan, tasks and checklist | Fleet issues-planner loop; read in `.agents/work-on-issues.md:48` |
| `agent:plan-build` | Trigger, issues | Plan then implement with no human step | Nothing runs it; see below |
| `agent:plan-check` | Trigger, issues | Second-model review of spec and plan | Fleet issues-reviewer loop |
| `agent:split` | Trigger, issues | Break an epic into child issues | Fleet issues-planner loop |
| `agent:research` | Trigger, issues | Explore code and sources to answer the issue | Fleet issues-planner loop |
| `agent:retro` | Trigger, issues | Analyse failed runs, propose prompt changes | Fleet issues-planner loop |
| `agent:area-map` | Trigger, issues | Write or refresh `.agents/areas/` files | Fleet issues-planner loop |
| `agent:review` | Trigger, PRs | Review the PR and post a verdict | Fleet prs-reviewer loop; mentioned in `.agents/work-on-issues.md:200` |
| `agent:verify` | Trigger, PRs | Run checks and acceptance-criteria coverage | Fleet prs-light loop |
| `agent:merge` | Trigger, PRs | Merge the PR when its gates pass | Fleet prs-light loop |
| `agent:revise` | Trigger, PRs | Apply review or verify findings on the PR | Fleet prs-builder loop |
| `agent:ci-fix` | Trigger, PRs | Fix failing CI checks on the PR | Fleet prs-builder loop |
| `agent:rebase` | Trigger, PRs | Update the PR from `dev`, resolve conflicts | Fleet prs-builder loop |
| `agent:done` | State | Finished and out of every dispatch query | `.agents/work-on-issues.md:30`, `.agents/work-on-issues.md:245`, `.agents/review_pr.md:55`, `.agents/review_pr.md:103` |

Claim and escalation labels are not `agent:*`-prefixed but belong to the same
contract: `in-progress` / `review-in-progress` (claim lock), `needs-human`
(blocked, needs a person), `backlog` (deferred by a person, never dispatched).
Both `.agents/` workflows filter on them; see `.agents/work-on-issues.md:30`
and `.agents/review_pr.md:55`.

`agent:build` on a PR starts nothing: it is an issue-side trigger and no PR
query reads it. Several parked PRs carry it alongside a dead PR trigger.

## Operator actions

A fleet loop picks up an issue or PR only when it carries an `agent:*` trigger
label and `kinged007` as assignee. Without both, nothing starts. When a person
does the work by hand, follow the matching row, then remove the trigger label
so a running loop never double-acts.

- Needs rebase: merge the base into the PR branch (never rebase, never
  force-push), resolve conflicts keeping both sides' intent, run the quality
  gate, push. Then remove `agent:rebase`.
- Needs a fix (red checks): fix the cause, run the quality gate, push. Then
  remove `agent:ci-fix`.
- Needs changes after review: apply the review findings, run the quality
  gate, push. Then remove `agent:revise`.
- Ready to merge: `agent:done` must already be on the PR (`.agents/review_pr.md`
  approval path), then merge. High-risk PRs are merged by the owner only.
  Then remove `agent:merge`.

## Labels that start no work

A fleet loop picks up an issue or PR only when it has an `agent:*` trigger
label and `kinged007` as assignee. One trigger has no loop behind it:

- `agent:plan-build` (no loop references it at all)
