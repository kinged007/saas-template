#!/usr/bin/env python3
"""Unit tests for scripts/merge_queue.py (stdlib unittest only).

Covers spec FR-003/FR-004/FR-014 and AC-8/AC-9/AC-10/AC-11:
trailer parsing, P0-then-FIFO selection, gate mapping, advisory
approval, and the exact merge/revert/close command strings.

Run: python3 scripts/test_merge_queue.py
"""

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import merge_queue as mq


class ParseTrailersTest(unittest.TestCase):
    def test_extracts_area_and_note(self):
        body = "Some text\n\nArea: api\nRelease-note: add Foobar endpoint\n"
        t = mq.parse_trailers(body)
        self.assertEqual(t.errors, [])
        self.assertEqual(t.area, "api")
        self.assertEqual(t.note, "add Foobar endpoint")

    def test_accepts_all_valid_areas(self):
        for area in ("api", "web", "db", "infra"):
            t = mq.parse_trailers(f"Area: {area}\nRelease-note: x\n")
            self.assertEqual(t.errors, [], area)
            self.assertEqual(t.area, area)

    def test_rejects_invalid_area(self):
        t = mq.parse_trailers("Area: mobile\nRelease-note: x\n")
        self.assertTrue(t.errors)
        self.assertIsNone(t.area)

    def test_rejects_missing_area(self):
        t = mq.parse_trailers("Release-note: x\n")
        self.assertTrue(any("Area" in e for e in t.errors))

    def test_rejects_missing_note(self):
        t = mq.parse_trailers("Area: api\n")
        self.assertTrue(any("Release-note" in e for e in t.errors))
        self.assertIsNone(t.note)

    def test_rejects_empty_note(self):
        t = mq.parse_trailers("Area: api\nRelease-note:   \n")
        self.assertTrue(t.errors)

    def test_rejects_duplicate_area(self):
        t = mq.parse_trailers("Area: api\nArea: web\nRelease-note: x\n")
        self.assertTrue(t.errors)

    def test_release_note_falls_back_to_title(self):
        # Scope update: a missing line never blocks a merge.
        note, fallback = mq.resolve_note("Area: api\n", "PR title here")
        self.assertEqual(note, "PR title here")
        self.assertTrue(fallback)
        note, fallback = mq.resolve_note(
            "Area: api\nRelease-note: real note\n", "PR title here"
        )
        self.assertEqual(note, "real note")
        self.assertFalse(fallback)


class SelectionTest(unittest.TestCase):
    def test_prefers_oldest_p0(self):
        prs = [
            {"number": 3, "is_p0": False, "merge_labeled_at": "2026-11-20T10:00:00Z"},
            {"number": 1, "is_p0": True, "merge_labeled_at": "2026-11-21T10:00:00Z"},
            {"number": 2, "is_p0": True, "merge_labeled_at": "2026-11-20T09:00:00Z"},
        ]
        self.assertEqual(mq.select_candidate(prs)["number"], 2)

    def test_fifo_without_p0(self):
        prs = [
            {"number": 5, "is_p0": False, "merge_labeled_at": "2026-11-21T10:00:00Z"},
            {"number": 4, "is_p0": False, "merge_labeled_at": "2026-11-20T10:00:00Z"},
        ]
        self.assertEqual(mq.select_candidate(prs)["number"], 4)

    def test_empty_queue_selects_nothing(self):
        self.assertIsNone(mq.select_candidate([]))


class GateMappingTest(unittest.TestCase):
    def _ctx(self, **over):
        ctx = {
            "base_ok": True,
            "mergeable": True,
            "checks_ok": True,
            "approval_ok": True,
            "area": "api",
            "note_ok": True,
        }
        ctx.update(over)
        return ctx

    def test_all_green_passes(self):
        results = mq.evaluate_gates(dev_ci_ok=True, pr=self._ctx())
        self.assertTrue(all(r.status == "pass" for r in results))

    def test_gate1_failure_changes_no_mark(self):
        results = mq.evaluate_gates(dev_ci_ok=False, pr=self._ctx())
        g1 = [r for r in results if r.number == 1][0]
        self.assertEqual(g1.status, "fail")
        self.assertIsNone(mq.failure_label(1))
        action = mq.failure_action(1)
        self.assertEqual(action.kind, "exit")

    def test_each_gate_maps_to_exact_label(self):
        # Gate: (ctx override, expected label).
        cases = {
            2: ({"base_ok": False}, "agent:revise"),
            3: ({"mergeable": False}, "agent:rebase"),
            4: ({"checks_ok": False}, "agent:ci-fix"),
            6: ({"area": None}, "agent:revise"),
        }
        for gate, (over, label) in cases.items():
            with self.subTest(gate=gate):
                results = mq.evaluate_gates(dev_ci_ok=True, pr=self._ctx(**over))
                failed = [r for r in results if r.number == gate][0]
                self.assertEqual(failed.status, "fail")
                self.assertEqual(mq.failure_label(gate), label)
                action = mq.failure_action(gate)
                self.assertEqual(action.kind, "relabel")
                self.assertEqual(action.label, label)
                self.assertIn(str(gate), action.comment)

    def test_gate_failure_posts_exactly_one_comment(self):
        for gate in (2, 3, 4, 6):
            with self.subTest(gate=gate):
                action = mq.failure_action(gate)
                self.assertEqual(len(action.comments), 1)

    def test_advisory_approval_never_blocks_stage1(self):
        # FR-007: evaluated and recorded, no relabel, no block.
        results = mq.evaluate_gates(
            dev_ci_ok=True, pr=self._ctx(approval_ok=False), enforce_approval=False
        )
        g5 = [r for r in results if r.number == 5][0]
        self.assertEqual(g5.status, "advisory")
        self.assertIsNone(mq.failure_label(5))
        self.assertTrue(mq.gates_allow_merge(results, enforce_approval=False))

    def test_enforcing_approval_blocks_and_routes_to_review(self):
        results = mq.evaluate_gates(
            dev_ci_ok=True, pr=self._ctx(approval_ok=False), enforce_approval=True
        )
        g5 = [r for r in results if r.number == 5][0]
        self.assertEqual(g5.status, "fail")
        self.assertEqual(mq.failure_label(5, enforce_approval=True), "agent:review")
        self.assertFalse(mq.gates_allow_merge(results, enforce_approval=True))


class HeadChecksTest(unittest.TestCase):
    """Gate 4 reads check runs (#1840): legacy `pending` with zero statuses
    must not fail a PR whose check runs are green."""

    def _run(self, name, status="completed", conclusion="success"):
        return {"name": name, "status": status, "conclusion": conclusion}

    def test_all_green_passes(self):
        runs = [self._run("api-test"),
                self._run("web-build", conclusion="skipped"),
                self._run("web-e2e", conclusion="neutral")]
        self.assertEqual(mq.classify_checks("success", runs), "pass")

    def test_one_failure_fails(self):
        runs = [self._run("api-test"),
                self._run("web-build", conclusion="failure")]
        self.assertEqual(mq.classify_checks("success", runs), "fail")

    def test_each_failing_conclusion_fails(self):
        for conclusion in ("failure", "cancelled", "timed_out", "action_required"):
            with self.subTest(conclusion=conclusion):
                runs = [self._run("api-test", conclusion=conclusion)]
                self.assertEqual(mq.classify_checks("success", runs), "fail")

    def test_pending_run_waits(self):
        for status in ("queued", "in_progress"):
            with self.subTest(status=status):
                runs = [self._run("api-test"),
                        self._run("web-build", status=status, conclusion=None)]
                self.assertEqual(mq.classify_checks("success", runs), "wait")

    def test_only_queue_job_pending_passes(self):
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "111"}):
            runs = [self._run("api-test"),
                    {"name": "merge", "status": "in_progress", "conclusion": None,
                     "details_url": "https://github.com/o/r/actions/runs/111/job/7"}]
            self.assertEqual(mq.classify_checks(None, runs), "pass")

    def test_real_check_named_merge_still_fails(self):
        # A failing check named `merge` from another workflow run carries a
        # different run id, so it is not the queue's own job and must count.
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "111"}):
            runs = [
                {"name": "merge", "status": "in_progress", "conclusion": None,
                 "details_url": "https://github.com/o/r/actions/runs/111/job/7"},
                {"name": "merge", "status": "completed", "conclusion": "failure",
                 "details_url": "https://github.com/o/r/actions/runs/999/job/2"},
            ]
            self.assertEqual(mq.classify_checks(None, runs), "fail")

    def test_check_named_merge_queue_is_not_skipped(self):
        runs = [self._run("merge-queue", conclusion="failure")]
        self.assertEqual(mq.classify_checks("success", runs), "fail")

    def test_zero_statuses_with_green_runs_passes(self):
        # The #1840 case: legacy API says pending with total_count 0.
        runs = [self._run("api-test"), self._run("web-build")]
        self.assertEqual(mq.classify_checks(None, runs), "pass")

    def test_no_signals_fails(self):
        # Zero check runs plus zero statuses: no CI ever reported, so fail
        # instead of waiting forever.
        self.assertEqual(mq.classify_checks(None, []), "fail")

    def test_only_queue_job_and_no_status_fails(self):
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "111"}):
            runs = [{"name": "merge", "status": "in_progress", "conclusion": None,
                     "details_url": "https://github.com/o/r/actions/runs/111/job/7"}]
            self.assertEqual(mq.classify_checks(None, runs), "fail")

    def test_stale_pending_fails(self):
        now = datetime(2026, 11, 24, 12, tzinfo=timezone.utc).timestamp()
        old = {"name": "api-test", "status": "queued", "conclusion": None,
               "started_at": "2026-11-24T09:00:00Z"}
        self.assertEqual(mq.classify_checks("success", [old], now=now), "fail")

    def test_fresh_pending_waits(self):
        now = datetime(2026, 11, 24, 12, tzinfo=timezone.utc).timestamp()
        fresh = {"name": "api-test", "status": "in_progress", "conclusion": None,
                 "started_at": "2026-11-24T11:55:00Z"}
        self.assertEqual(mq.classify_checks("success", [fresh], now=now), "wait")

    def test_pending_without_started_at_waits(self):
        runs = [self._run("api-test", status="queued", conclusion=None)]
        self.assertEqual(mq.classify_checks("success", runs), "wait")

    def test_failing_status_fails(self):
        self.assertEqual(mq.classify_checks("failure", [self._run("api-test")]), "fail")
        self.assertEqual(mq.classify_checks("error", []), "fail")

    def test_pending_status_waits(self):
        runs = [self._run("api-test")]
        self.assertEqual(mq.classify_checks("pending", runs), "wait")

    def test_head_checks_ignores_empty_legacy_status(self):
        q = mq.MergeQueue(repo="o/r", base="dev")
        q.commit_status = lambda sha: "pending"  # noqa: SLF001
        q.commit_status_count = lambda sha: 0  # noqa: SLF001
        q.check_runs = lambda sha: [self._run("api-test")]  # noqa: SLF001
        self.assertEqual(q.head_checks("sha1"), "pass")

    def test_head_checks_api_error_waits_without_legacy_fallback(self):
        q = mq.MergeQueue(repo="o/r", base="dev")
        q.commit_status = lambda sha: "success"  # noqa: SLF001
        q.commit_status_count = lambda sha: 1  # noqa: SLF001

        def boom(sha):
            raise RuntimeError("403")
        q.check_runs = boom  # noqa: SLF001
        # Legacy success alone would pass; the checks-API outage must wait.
        self.assertEqual(q.head_checks("sha1"), "wait")

    def test_run_once_waits_without_relabel_on_pending(self):
        q = mq.MergeQueue(repo="o/r", base="dev")
        q.dev_head = lambda: "devsha"  # noqa: SLF001
        q.latest_ci_run = lambda: {"headSha": "devsha", "conclusion": "success",  # noqa: SLF001
                                   "status": "completed", "url": "u", "databaseId": 1}
        q.open_queue = lambda: [{"number": 7, "title": "T", "baseRefName": "dev",  # noqa: SLF001
                                 "headRefOid": "sha7", "mergeable": "MERGEABLE",
                                 "body": "Area: infra\nRelease-note: x\n"}]
        q.head_checks = lambda sha: "wait"  # noqa: SLF001
        q.approval_at_head = lambda n, sha: True  # noqa: SLF001
        mutated = []
        q._mutate = lambda args: mutated.append(args) or ""  # noqa: SLF001
        self.assertEqual(q.run_once(), "gate4-wait")
        self.assertEqual(mutated, [])


class CommandStringTest(unittest.TestCase):
    def test_squash_uses_explicit_subject_and_body(self):
        args = mq.build_merge_args(12, "Add thing", "api", "take it")
        self.assertIn("--squash", args)
        self.assertIn("--subject", args)
        self.assertIn("Add thing (#12)", args)
        body = args[args.index("--body") + 1]
        self.assertIn("Area: api", body)
        self.assertIn("Release-note: take it", body)
        joined = " ".join(args)
        self.assertNotIn("--merge", joined)
        self.assertNotIn("--rebase", joined)

    def test_revert_keeps_lineage_line(self):
        body = mq.build_revert_body("abc123", "https://run/1")
        self.assertIn("This reverts commit abc123.", body)
        self.assertIn("https://run/1", body)
        subject = mq.build_revert_subject("Add thing (#12)")
        self.assertEqual(subject, "revert: Add thing (#12) — dev CI failed")

    def test_close_comment_names_sha(self):
        self.assertIn("deadbeef", mq.build_close_comment("deadbeef"))

    def test_reopen_comment_carries_run_url(self):
        comment = mq.build_reopen_comment("https://run/9")
        self.assertIn("https://run/9", comment)
        self.assertIn("agent:ci-fix", comment)

    def test_auth_uses_fleet_token_only(self):
        # FR-012: every push/merge authenticates via the FLEET_TOKEN-fed
        # GH_TOKEN; the ephemeral workflow credential is never consulted.
        src = Path(__file__).with_name("merge_queue.py").read_text()
        self.assertIn("GH_TOKEN", src)
        self.assertIn("FLEET_TOKEN", src)
        self.assertNotIn("GITHUB_TOKEN", src)


class RedDevRecoveryTest(unittest.TestCase):
    def test_closing_issues_filters_by_state(self):
        q = mq.MergeQueue(repo="o/r", base="dev")
        nodes = '[{"number": 11, "state": "CLOSED"}, {"number": 12, "state": "OPEN"}]'
        q._read = lambda args: nodes  # noqa: SLF001
        self.assertEqual(q.closing_issues(7), [12])
        self.assertEqual(q.closing_issues(7, want="CLOSED"), [11])

    def test_handle_red_dev_reopens_closed_issues(self):
        q = mq.MergeQueue(repo="o/r", base="dev")
        calls = {}
        q.rerun_failed = lambda run_id: calls.setdefault("rerun", run_id)  # noqa: SLF001
        q.wait_for_rerun_start = lambda run_id, **kw: True  # noqa: SLF001
        q.wait_for_run = lambda run_id, **kw: "failure"  # noqa: SLF001
        q.dev_head = lambda: "sha1"  # noqa: SLF001
        q._read = lambda args: "Add thing (#12)"  # noqa: SLF001 - git log subject
        q.revert_newest = lambda *a: calls.setdefault("revert", a)  # noqa: SLF001
        seen = {}
        def fake_closing(n, want="OPEN"):
            seen["want"] = want
            self.assertEqual(n, 12)
            return [11]
        q.closing_issues = fake_closing  # noqa: SLF001
        q.reopen_issues = lambda nums, url: seen.update(numbers=nums, url=url)  # noqa: SLF001
        run = {"databaseId": 99, "url": "https://run/9", "headSha": "sha1"}
        self.assertEqual(q.handle_red_dev(run), "reverted")
        self.assertEqual(calls["rerun"], 99)
        self.assertIn("revert", calls)
        self.assertEqual(seen["want"], "CLOSED")
        self.assertEqual(seen["numbers"], [11])
        self.assertEqual(seen["url"], "https://run/9")

    def test_unknown_label_time_sorts_last(self):
        prs = [
            {"number": 1, "is_p0": False},
            {"number": 2, "is_p0": False, "merge_labeled_at": "2026-11-20T10:00:00Z"},
        ]
        self.assertEqual(mq.select_candidate(prs)["number"], 2)

    def test_stale_failed_run_exits_without_red_path(self):
        q = mq.MergeQueue(repo="o/r", base="dev")
        q.dev_head = lambda: "newsha"  # noqa: SLF001
        q.latest_ci_run = lambda: {"headSha": "oldsha", "conclusion": "failure",  # noqa: SLF001
                                   "status": "completed", "url": "u", "databaseId": 1}
        called = []
        q.handle_red_dev = lambda run: called.append(run) or "reverted"  # noqa: SLF001
        self.assertEqual(q.run_once(), "gate1-exit")
        self.assertEqual(called, [])


class DryRunNoMutationTest(unittest.TestCase):
    def test_dry_run_performs_no_mutation(self):
        calls = []

        def fake_run(args, mutating):
            calls.append((tuple(args), mutating))
            if args[:2] == ["gh", "pr"]:
                return (
                    '[{"number": 7, "title": "T", "baseRefName": "dev", '
                    '"headRefOid": "sha7", "mergeable": "MERGEABLE"}]'
                )
            if args[:2] == ["gh", "api"]:
                return "[]"
            return ""

        q = mq.MergeQueue(repo="o/r", base="dev", dry_run=True)
        q._run = fake_run  # noqa: SLF001 - stub the subprocess boundary
        q.run_once()
        mutating = [c for c in calls if c[1]]
        self.assertEqual(mutating, [])


if __name__ == "__main__":
    unittest.main()
