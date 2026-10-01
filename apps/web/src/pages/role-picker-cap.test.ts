import assert from "node:assert/strict";
import { test } from "node:test";

import { rolePickerCapNotice } from "./role-picker-cap.ts";

// The role endpoints answer with one capped page. When a workspace has more
// roles than that page holds, both pickers on MembersPage render a short list,
// so each has to say so with the same sentence RolesSection already uses.
test("no notice while the fetch covers every role", () => {
  assert.equal(rolePickerCapNotice(5, 5), null);
  assert.equal(rolePickerCapNotice(0, 0), null);
});

test("the owner role being filtered out of the pickers is not a cap", () => {
  assert.equal(rolePickerCapNotice(4, 5), null);
});

test("a short page discloses itself with the RolesSection wording", () => {
  assert.equal(rolePickerCapNotice(105, 100), "Showing 100 of 105 roles.");
});