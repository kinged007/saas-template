import assert from "node:assert/strict";
import { test } from "node:test";

import type { JobRunStatus } from "@/types";
import type { BadgeVariant, StatusBadgeStatus } from "./status-badge.ts";
import { jobRunBadgeVariant, statusBadgeVariant } from "./status-badge.ts";

test("only an expired invitation is destructive", () => {
  assert.equal(statusBadgeVariant("expired"), "destructive");
});

test("only a pending invitation is a warning", () => {
  assert.equal(statusBadgeVariant("pending"), "warning");
});

test("member, invitation and account statuses keep rendering as secondary", () => {
  const secondary: StatusBadgeStatus[] = [
    "active",
    "invited",
    "suspended",
    "accepted",
    "declined",
    "revoked",
    "disabled",
  ];
  for (const status of secondary) {
    assert.equal(statusBadgeVariant(status), "secondary", status);
  }
});

test("a runtime-unknown status falls back to secondary", () => {
  // @ts-expect-error the badge only accepts the statuses the API documents.
  assert.equal(statusBadgeVariant("archived"), "secondary");
});

test("every job run status keeps its variant", () => {
  const expected: Record<JobRunStatus, BadgeVariant> = {
    pending: "warning",
    running: "warning",
    success: "success",
    failed: "destructive",
    timed_out: "destructive",
  };
  for (const status of Object.keys(expected) as JobRunStatus[]) {
    assert.equal(jobRunBadgeVariant(status), expected[status], status);
  }
});

test("a runtime-unknown job run status falls back to secondary", () => {
  // @ts-expect-error the badge only accepts the statuses the API documents.
  assert.equal(jobRunBadgeVariant("retrying"), "secondary");
});
