import assert from "node:assert/strict";
import { test } from "node:test";

import { userDetailMessage } from "./user-detail-message.ts";
import type { AdminUserDetail } from "./users-toggle.ts";

const withDetail: AdminUserDetail = {
  id: "u-1",
  email: "a@example.com",
  display_name: "Ada",
  is_active: true,
  is_superuser: false,
  workspaces: [{ id: "w-1", name: "W", slug: "w", role: "owner" }],
};
const settled = { isPending: false };
const pending = { isPending: true };

test("a rendered detail needs no message", () => {
  assert.equal(userDetailMessage(withDetail, true, settled), null);
});

test("a read still in flight needs no message", () => {
  assert.equal(userDetailMessage(undefined, true, pending), null);
});

test("a closed panel needs no message", () => {
  assert.equal(userDetailMessage(undefined, false, settled), null);
});

test("a selected row with no detail says the read is unavailable", () => {
  assert.equal(
    userDetailMessage(undefined, true, settled),
    "User details could not be loaded.",
  );
});
