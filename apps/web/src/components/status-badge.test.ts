import assert from "node:assert/strict";
import { test } from "node:test";

import type { StatusBadgeStatus } from "./status-badge.ts";
import { statusBadgeVariant } from "./status-badge.ts";

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

test("the badge renders the raw status, so an unknown value is a compile error", () => {
  // @ts-expect-error the badge only accepts the statuses the API documents.
  assert.equal(statusBadgeVariant("archived"), undefined);
});