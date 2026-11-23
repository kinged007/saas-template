import assert from "node:assert/strict";
import { test } from "node:test";

import { resolveTargetUserId } from "./target-user.ts";

test("no route id is the self page, not a target", () => {
  assert.equal(resolveTargetUserId(null, "user-1"), null);
});

test("your own id is the self page, not a delegated target", () => {
  assert.equal(resolveTargetUserId("user-1", "user-1"), null);
});

test("another member's id is the target", () => {
  assert.equal(resolveTargetUserId("user-2", "user-1"), "user-2");
});

test("an id stays a target while the identity is still loading", () => {
  assert.equal(resolveTargetUserId("user-2", undefined), "user-2");
});
