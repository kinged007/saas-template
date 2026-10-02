import assert from "node:assert/strict";
import { test } from "node:test";

import type { Member } from "@/types";
import {
  resolveTransferTarget,
  transferCapNotice,
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
  // A workspace created before the case-insensitive API check can hold `Owner`.
  const legacyOwner = member({ membership_id: "m-3", role: "Owner" });
  assert.deepEqual(
    transferEligibleMembers([owner, legacyOwner, admin, suspended]).map((m) => m.membership_id),
    ["m-1"],
  );
});

test("transferEligibleMembers drops a status it has never seen", () => {
  const unknown = member({
    membership_id: "m-3",
    status: "archived" as unknown as Member["status"],
  });
  assert.deepEqual(transferEligibleMembers([unknown]), []);
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

/** `page` members: `owners` owners, `suspended` suspended, the rest eligible. */
const page = (count: number, owners = 0, suspended = 0): Member[] =>
  Array.from({ length: count }, (_, i) =>
    member({
      membership_id: `m-${i}`,
      role: i < owners ? "owner" : "admin",
      status: i < owners + suspended ? "suspended" : "active",
    }),
  );

test("transferCapNotice stays silent while the fetch covers the workspace", () => {
  // The whole workspace in hand: nothing was dropped, so nothing to disclose.
  assert.equal(transferCapNotice(3, page(3, 1)), null);
  // A page exactly at the endpoint ceiling is not truncated.
  assert.equal(transferCapNotice(100, page(100)), null);
  assert.equal(transferCapNotice(0, []), null);
});

test("transferCapNotice counts the offer, not the page", () => {
  // 143 members in the workspace, 100 fetched, of which 1 owner and 2 suspended.
  assert.equal(transferCapNotice(143, page(100, 1, 2)), "Showing 97 of 140 members.");
});

test("transferCapNotice uses one list for both numbers", () => {
  // Same numbers as the role picker: 105 in the workspace, 99 of the page pickable.
  assert.equal(transferCapNotice(105, page(100, 1)), "Showing 99 of 104 members.");
});

test("transferCapNotice never reports a negative tail", () => {
  // A stale total can sit below the rows already in hand; the denominator floors
  // at 0 instead of going negative. A missing X-Total-Count falls back to the
  // page length, which is the ceiling case above and already silent.
  assert.equal(transferCapNotice(0, page(100)), null);
  assert.equal(transferCapNotice(1, page(3, 1)), null);
});

// Coverage: these are the pure helpers behind the transfer Select. The effect
// that clears a stale id in GeneralSection.tsx is wiring over
// resolveTransferTarget, not a tested unit — `node --test` cannot load .tsx
// (see AGENTS.md), so that wiring is verified by hand; e2e/transfer-cap.spec.ts
// covers the cap notice, not the clearing effect. What the wiring relies on is
// covered above: an unresolvable id yields undefined.
