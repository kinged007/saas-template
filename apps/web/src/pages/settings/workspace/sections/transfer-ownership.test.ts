import assert from "node:assert/strict";
import { test } from "node:test";

import type { Member } from "@/types";
import {
  resolveTransferTarget,
  transferCandidateMessage,
  transferEligibleMembers,
} from "./transfer-ownership.ts";

const member = (over: Partial<Member> = {}): Member => ({
  id: "u-1",
  email: "a@example.com",
  display_name: "A B",
  membership_id: "m-1",
  role_id: "r-1",
  role: "admin",
  status: "active",
  ...over,
});

test("transferEligibleMembers offers active non-owners only", () => {
  const owner = member({ membership_id: "m-0", role: "owner" });
  const admin = member({ membership_id: "m-1" });
  const suspended = member({ membership_id: "m-2", status: "suspended" });
  assert.deepEqual(
    transferEligibleMembers([owner, admin, suspended]).map((m) => m.membership_id),
    ["m-1"],
  );
});

test("resolveTransferTarget returns the picked candidate", () => {
  const admin = member({ membership_id: "m-1" });
  assert.equal(resolveTransferTarget([admin], "m-1"), admin);
});

test("resolveTransferTarget disarms when the id outlives the candidate set", () => {
  // The id survives a refetch, but the member was deactivated: the refetched
  // candidate list no longer names them, so the action must not fire.
  const before = [member({ membership_id: "m-1" })];
  const after = transferEligibleMembers([
    member({ membership_id: "m-1", status: "suspended" }),
  ]);
  assert.equal(resolveTransferTarget(before, "m-1")?.membership_id, "m-1");
  assert.equal(resolveTransferTarget(after, "m-1"), undefined);
  assert.equal(resolveTransferTarget([], "m-1"), undefined);
});

test("resolveTransferTarget is disarmed before a selection is made", () => {
  assert.equal(resolveTransferTarget([member()], ""), undefined);
});

test("transferCandidateMessage reads the query error instead of advising an invite", () => {
  const base = { isPending: false, isError: true, loaded: 0, total: 0 };
  const message = transferCandidateMessage({ ...base, error: new Error("500 Internal Server Error") });
  assert.match(message, /^Could not load members: 500 Internal Server Error\./);
  assert.doesNotMatch(message, /invite one first/);
});

test("transferCandidateMessage never contradicts a truncated list with an invite prompt", () => {
  const message = transferCandidateMessage({
    isPending: false,
    isError: false,
    error: null,
    loaded: 100,
    total: 124,
  });
  assert.match(message, /100 members loaded here\. The other 24 are not listed/);
  assert.doesNotMatch(message, /invite one first/);
});

test("transferCandidateMessage invites only when the whole list was loaded and empty", () => {
  const empty = { isPending: false, isError: false, error: null };
  assert.match(transferCandidateMessage({ ...empty, loaded: 3, total: 3 }), /invite one first/);
  assert.equal(
    transferCandidateMessage({ ...empty, isPending: true, loaded: 0, total: 0 }),
    "Loading members…",
  );
});
