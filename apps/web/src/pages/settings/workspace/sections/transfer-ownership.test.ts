import assert from "node:assert/strict";
import { test } from "node:test";

import type { Member } from "@/types";
import {
  resolveTransferTarget,
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

// transfer_ownership rejects a target that already owns the workspace and calls
// the owner the row whose name folds to `owner` (is_owner_role_name), so a row
// spelled `Owner` is not offered as a target for itself.
test("transferEligibleMembers drops the case-variant owner row too", () => {
  const legacyOwner = member({ membership_id: "m-0", role: "Owner" });
  const admin = member({ membership_id: "m-1" });
  assert.deepEqual(
    transferEligibleMembers([legacyOwner, admin]).map((m) => m.membership_id),
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

// Coverage: these are the pure helpers behind the transfer Select. The effect
// that clears a stale id in GeneralSection.tsx is wiring over
// resolveTransferTarget, not a tested unit — `node --test` cannot load .tsx
// (see AGENTS.md), so that wiring is verified by hand. What it relies on is
// covered above: an unresolvable id yields undefined.
