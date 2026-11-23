#!/usr/bin/env python3
"""Merge queue: squash-merge approved PRs into the integration branch.

One scheduler run merges at most one PR; gate failures skip to the next
candidate. All decision logic lives here so it runs locally with --dry-run
and is unit testable; .github/workflows/merge-queue.yml only declares
triggers, concurrency, and the call to this script.

Standard library only. All gh/git subprocess calls go through
MergeQueue._run so --dry-run can prove zero mutations.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field

INTEGRATION_BRANCH = "dev"
MERGE_LABEL = "agent:merge"
P0_LABEL = "P0"
VALID_AREAS = ("api", "web", "db", "infra")

AREA_RE = re.compile(r"^\s*(?:\*\*)?Area:(?:\*\*)?\s*(.+?)\s*$", re.MULTILINE)
NOTE_RE = re.compile(r"^\s*(?:\*\*)?Release-note:(?:\*\*)?\s*(.*?)\s*$", re.MULTILINE)

# Gate number -> follow-up label on failure. Gate 1 changes no mark (the
# next `ci` completion retries); gate 5 is advisory in Stage 1 (FR-007) so
# it carries a label only when approval is enforced (Stage 2).
GATE_LABELS = {
    2: "agent:revise",  # base is not the integration branch
    3: "agent:rebase",  # textual conflict
    4: "agent:ci-fix",  # PR checks red
    5: "agent:review",  # approval missing/stale (enforcing stage only)
    6: "agent:revise",  # Area line invalid
}
GATE_NAMES = {
    1: "dev CI green",
    2: "base is dev",
    3: "mergeable",
    4: "PR checks green",
    5: "approval at head",
    6: "trailers",
}


@dataclass
class Trailers:
    area: str | None
    note: str | None
    errors: list


def parse_trailers(body):
    """Extract and validate the Area:/Release-note: trailer lines."""
    body = body or ""
    areas = AREA_RE.findall(body)
    notes = NOTE_RE.findall(body)
    errors = []
    area = None
    note = None
    if len(areas) > 1:
        errors.append("multiple Area: lines")
    elif not areas or not areas[0].strip():
        errors.append("missing Area: line")
    elif areas[0].strip().lower() not in VALID_AREAS:
        errors.append("invalid Area: %r (want one of %s)" % (areas[0].strip(), "/".join(VALID_AREAS)))
    else:
        area = areas[0].strip().lower()
    if len(notes) > 1:
        errors.append("multiple Release-note: lines")
    elif not notes or not notes[0].strip():
        errors.append("missing Release-note: line")
    else:
        note = notes[0].strip()
    return Trailers(area=area, note=note, errors=errors)


def resolve_note(body, title):
    """Release-note value for the squash body.

    Scope rule: a missing line never blocks a merge; the PR title is used.
    """
    parsed = parse_trailers(body)
    if parsed.note:
        return parsed.note, False
    return (title or "").strip(), True


def select_candidate(prs):
    """Oldest P0 PR with agent:merge, else oldest agent:merge (FIFO)."""
    if not prs:
        return None
    key = lambda p: (p.get("merge_labeled_at") or "", p["number"])  # noqa: E731
    p0 = [p for p in prs if p.get("is_p0")]
    pool = p0 if p0 else list(prs)
    return sorted(pool, key=key)[0]


@dataclass
class GateResult:
    number: int
    status: str  # pass | fail | advisory
    detail: str


def evaluate_gates(dev_ci_ok, pr, enforce_approval=False):
    """Evaluate the six merge gates in fixed order (pure, testable)."""
    results = []
    results.append(
        GateResult(1, "pass" if dev_ci_ok else "fail",
                   "latest ci on dev is green" if dev_ci_ok else "dev CI not green")
    )
    results.append(
        GateResult(2, "pass" if pr.get("base_ok") else "fail",
                   "base is dev" if pr.get("base_ok") else "base is %r" % pr.get("base"))
    )
    results.append(
        GateResult(3, "pass" if pr.get("mergeable") else "fail",
                   "mergeable" if pr.get("mergeable") else "textual conflict")
    )
    results.append(
        GateResult(4, "pass" if pr.get("checks_ok") else "fail",
                   "checks green" if pr.get("checks_ok") else "checks red at head")
    )
    if pr.get("approval_ok"):
        results.append(GateResult(5, "pass", "approved at head"))
    elif enforce_approval:
        results.append(GateResult(5, "fail", "no approval at head"))
    else:
        # Stage 1: advisory — evaluated and recorded, never blocks (FR-007).
        results.append(GateResult(5, "advisory", "no approval at head (advisory)"))
    area_ok = pr.get("area") in VALID_AREAS
    results.append(
        GateResult(6, "pass" if area_ok else "fail",
                   "Area: %s" % pr.get("area") if area_ok else "bad Area: %r" % pr.get("area"))
    )
    return results


def gates_allow_merge(results, enforce_approval=False):
    return all(r.status in ("pass", "advisory") for r in results)


def failure_label(gate, enforce_approval=False):
    if gate == 1:
        return None
    if gate == 5 and not enforce_approval:
        return None
    return GATE_LABELS.get(gate)


@dataclass
class FailureAction:
    kind: str  # exit | relabel
    label: str | None
    comment: str
    comments: list = field(default_factory=list)

    def __post_init__(self):
        if self.kind == "relabel":
            self.comments = [self.comment]


def failure_action(gate, detail="", enforce_approval=False):
    if gate == 1:
        return FailureAction(kind="exit", label=None, comment="")
    label = failure_label(gate, enforce_approval)
    comment = "Merge queue: check %d (%s) failed%s. Removed %s, added %s." % (
        gate, GATE_NAMES[gate],
        (": " + detail) if detail else "",
        MERGE_LABEL, label,
    )
    return FailureAction(kind="relabel", label=label, comment=comment)


def build_merge_args(n, title, area, note):
    return [
        "gh", "pr", "merge", str(n), "--squash",
        "--subject", "%s (#%s)" % (title, n),
        "--body", "Area: %s\nRelease-note: %s" % (area, note),
    ]


def build_revert_subject(subject):
    return "revert: %s — dev CI failed" % subject


def build_revert_body(sha, run_url):
    return "This reverts commit %s.\n\ndev CI run: %s" % (sha, run_url)


def build_close_comment(sha):
    return "Merged as %s." % sha


def build_reopen_comment(run_url):
    return "Reverted: dev CI failed (%s). Fix with agent:ci-fix." % run_url


class MergeQueue:
    def __init__(self, repo, base=INTEGRATION_BRANCH, dry_run=False, enforce_approval=False):
        self.repo = repo
        self.base = base
        self.dry_run = dry_run
        self.enforce_approval = enforce_approval

    def _run(self, args, mutating=False):
        if mutating and self.dry_run:
            raise AssertionError("mutation attempted in --dry-run: %r" % (args,))
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError("command failed: %s\n%s" % (" ".join(args), proc.stderr))
        return proc.stdout.strip()

    def _read(self, args):
        return self._run(args, mutating=False)

    def _mutate(self, args):
        if self.dry_run:
            print("  [dry-run] would run: %s" % " ".join(args))
            return ""
        return self._run(args, mutating=True)

    def require_token(self):
        token = os.environ.get("GH_TOKEN", "")
        if not token:
            raise SystemExit(
                "missing GH_TOKEN: export it from secrets.FLEET_TOKEN "
                "(never the ephemeral workflow credential)"
            )
        return token

    # -- live reads -----------------------------------------------------

    def open_queue(self):
        out = self._read([
            "gh", "pr", "list", "--repo", self.repo, "--state", "open",
            "--label", MERGE_LABEL, "--base", self.base,
            "--json", "number,title,baseRefName,headRefOid,mergeable,labels,body",
        ])
        prs = json.loads(out or "[]")
        for pr in prs:
            names = [lab["name"] for lab in pr.get("labels", [])]
            pr["is_p0"] = P0_LABEL in names
            pr["merge_labeled_at"] = self.label_time(pr["number"])
        return prs

    def label_time(self, n):
        out = self._read([
            "gh", "api", "repos/%s/issues/%d/events" % (self.repo, n),
            "--paginate", "-q",
            '[.[] | select(.event=="labeled" and .label.name=="%s")]'
            " | max_by(.created_at) | .created_at // empty" % MERGE_LABEL,
        ])
        return out.strip().strip('"') or ""

    def dev_head(self):
        return self._read([
            "gh", "api", "repos/%s/branches/%s" % (self.repo, self.base),
            "-q", ".commit.sha",
        ])

    def latest_ci_run(self):
        out = self._read([
            "gh", "run", "list", "--repo", self.repo, "--workflow", "ci",
            "--branch", self.base, "--limit", "1",
            "--json", "databaseId,status,conclusion,headSha,url",
        ])
        runs = json.loads(out or "[]")
        return runs[0] if runs else None

    def commit_status(self, sha):
        return self._read([
            "gh", "api", "repos/%s/commits/%s/status" % (self.repo, sha),
            "-q", ".state",
        ])

    def approval_at_head(self, n, head_sha):
        out = self._read([
            "gh", "api", "repos/%s/pulls/%d/reviews" % (self.repo, n),
            "--paginate", "-q",
            '[.[] | select(.state=="APPROVED" and .commit_id=="%s")] | length' % head_sha,
        ])
        return (out.strip() not in ("", "0"))

    def closing_issues(self, n):
        """Open issue numbers the PR resolves (GraphQL closingIssuesReferences)."""
        owner, name = self.repo.split("/", 1)
        query = (
            "{repository(owner:%s,name:%s){pullRequest(number:%d)"
            "{closingIssuesReferences(first:20){nodes{number,state}}}}}"
        ) % (json.dumps(owner), json.dumps(name), n)
        out = self._read([
            "gh", "api", "graphql", "-f", "query=" + query,
            "--jq", ".data.repository.pullRequest.closingIssuesReferences.nodes",
        ])
        try:
            nodes = json.loads(out or "[]")
        except json.JSONDecodeError:
            return []
        return [x["number"] for x in nodes
                if x.get("state") == "OPEN" and isinstance(x.get("number"), int)]

    # -- live mutations --------------------------------------------------

    def relabel_failure(self, n, action):
        self._mutate(["gh", "pr", "edit", str(n), "--repo", self.repo,
                      "--remove-label", MERGE_LABEL, "--add-label", action.label])
        self._mutate(["gh", "pr", "comment", str(n), "--repo", self.repo,
                      "--body", action.comment])

    def squash_merge(self, n, title, area, note):
        self._mutate(build_merge_args(n, title, area, note)[:3]
                      + ["--repo", self.repo] + build_merge_args(n, title, area, note)[3:])

    def close_issues(self, numbers, sha):
        for num in numbers:
            state = self._read(["gh", "issue", "view", str(num),
                                "--repo", self.repo, "--json", "state", "-q", ".state"])
            if state == "CLOSED":
                continue
            self._mutate(["gh", "issue", "close", str(num), "--repo", self.repo,
                          "--comment", build_close_comment(sha)])

    def rerun_failed(self, run_id):
        self._mutate(["gh", "run", "rerun", "--repo", self.repo,
                      "--failed", str(run_id)])

    def wait_for_run(self, run_id, timeout_s=600, interval_s=30):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            out = self._read(["gh", "run", "view", str(run_id), "--repo", self.repo,
                              "--json", "status,conclusion", "-q",
                              '"\\(.status) \\(.conclusion)"'])
            status, _, conclusion = out.partition(" ")
            if status == "completed":
                return conclusion
            time.sleep(interval_s)
        return "timed_out"

    def revert_newest(self, subject, sha, run_url):
        self._mutate(["git", "revert", "--no-commit", sha])
        self._mutate(["git", "commit", "-m", build_revert_subject(subject),
                      "-m", build_revert_body(sha, run_url)])
        self._mutate(["git", "push", "origin", "HEAD:%s" % self.base])

    def reopen_issues(self, numbers, run_url):
        for num in numbers:
            self._mutate(["gh", "issue", "reopen", str(num), "--repo", self.repo,
                          "--comment", build_reopen_comment(run_url)])
            self._mutate(["gh", "issue", "edit", str(num), "--repo", self.repo,
                          "--add-label", "agent:ci-fix"])

    # -- flows ------------------------------------------------------------

    def handle_red_dev(self, run):
        """Retry failed jobs once, then revert the newest squash (FR-010/11)."""
        print("dev CI red: %s — rerunning failed jobs once" % run["url"])
        self.rerun_failed(run["databaseId"])
        if self.dry_run:
            print("  [dry-run] gate 1 (red-dev path): would poll, then revert on red")
            return "dry-run"
        conclusion = self.wait_for_run(run["databaseId"])
        if conclusion == "success":
            print("retry green — no revert, resuming")
            return "green"
        head = self.dev_head()
        subject = self._read(["git", "log", "-1", "--format=%s", head]) if head else "unknown"
        self.revert_newest(subject, head, run["url"])
        match = re.search(r"\(#(\d+)\)\s*$", subject or "")
        numbers = self.closing_issues(int(match.group(1))) if match else []
        self.reopen_issues(numbers, run["url"])
        return "reverted"

    def pr_gate_inputs(self, pr):
        trailers = parse_trailers(pr.get("body", ""))
        note, fallback = resolve_note(pr.get("body", ""), pr.get("title", ""))
        head = pr.get("headRefOid", "")
        return {
            "base_ok": pr.get("baseRefName") == self.base,
            "base": pr.get("baseRefName"),
            "mergeable": pr.get("mergeable") == "MERGEABLE",
            "checks_ok": self.commit_status(head) == "success" if head else False,
            "approval_ok": self.approval_at_head(pr["number"], head) if head else False,
            "area": trailers.area,
            "note": note,
            "note_fallback": fallback,
        }

    def run_once(self):
        # Gate 1 first: latest ci on the dev head must be green.
        head = self.dev_head()
        run = self.latest_ci_run()
        if not run or run.get("headSha") != head or run.get("conclusion") != "success":
            url = (run or {}).get("url", "none")
            if run and run.get("conclusion") not in (None, "success") and run.get("status") == "completed":
                print("gate 1 dev-CI: FAIL (%s) — entering red-dev path" % url)
                return self.handle_red_dev(run)
            print("gate 1 dev-CI: FAIL (missing or stale for %s) — exit, no mark change" % head)
            return "gate1-exit"
        print("gate 1 dev-CI: pass (%s)" % head)

        queue = self.open_queue()
        if not queue:
            print("queue empty — nothing to merge")
            return "empty"
        while queue:
            pr = select_candidate(queue)
            queue = [p for p in queue if p["number"] != pr["number"]]
            print("candidate: #%d %s" % (pr["number"], pr.get("title", "")))
            inputs = self.pr_gate_inputs(pr)
            results = evaluate_gates(True, inputs, self.enforce_approval)
            for r in results:
                print("  gate %d %s: %s — %s" % (r.number, GATE_NAMES[r.number], r.status, r.detail))
            if inputs.get("note_fallback"):
                print("  note: PR body has no release note — using PR title")
            if gates_allow_merge(results, self.enforce_approval):
                note = inputs["note"]
                print("all gates pass — squash-merging #%d" % pr["number"])
                self.squash_merge(pr["number"], pr.get("title", ""), inputs["area"], note)
                if self.dry_run:
                    print("  [dry-run] would close linked issues naming the squash SHA")
                    return "merged-dry-run"
                numbers = self.closing_issues(pr["number"])
                new_head = self.dev_head()
                self.close_issues(numbers, new_head)
                return "merged"
            for r in results:
                if r.status == "fail":
                    action = failure_action(r.number, r.detail, self.enforce_approval)
                    print("  gate %d failed — %s %s" % (r.number, action.kind, action.label or ""))
                    self.relabel_failure(pr["number"], action)
                    break
        return "no-mergeable-candidate"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Merge queue into dev.")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the selection and per-gate results; mutate nothing")
    parser.add_argument("--base", default=INTEGRATION_BRANCH)
    parser.add_argument("--repo", default="")
    parser.add_argument("--enforce-approval", action="store_true",
                        help="Stage 2: approval mismatch blocks and routes to agent:review")
    args = parser.parse_args(argv)
    repo = args.repo or subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    if not repo:
        raise SystemExit("cannot determine repo: pass --repo owner/name")
    queue = MergeQueue(repo=repo, base=args.base, dry_run=args.dry_run,
                       enforce_approval=args.enforce_approval)
    if not args.dry_run:
        queue.require_token()
    print("merge-queue --dry-run" if args.dry_run else "merge-queue")
    print("repo: %s base: %s" % (repo, args.base))
    print("result: %s" % queue.run_once())
    return 0


if __name__ == "__main__":
    sys.exit(main())
