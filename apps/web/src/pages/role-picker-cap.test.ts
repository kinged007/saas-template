import assert from "node:assert/strict";
import { test } from "node:test";

import { rolePickerCapNotice } from "./role-picker-cap.ts";
import type { Role } from "../types.ts";

const role = (id: string, name: string): Role => ({
  id,
  workspace_id: "ws-1",
  name,
  permissions: [],
  system: false,
});

/** A full picker page: the owner role first, then `rest` custom roles. */
const page = (rest: number): Role[] => [
  role("1", "owner"),
  ...Array.from({ length: rest }, (_, i) => role(String(i + 2), `r${i}`)),
];

// The role endpoints answer with one capped page. When a workspace has more
// roles than that page holds, both pickers on MembersPage render a short list,
// so each has to say so with the same sentence RolesSection already uses. The
// pickers drop the owner role, so the counts have to be the offer's, not the
// page's: a notice counting a role the dropdown never lists is a wrong notice.
test("no notice while the fetch covers every role", () => {
  assert.equal(rolePickerCapNotice(2, [role("1", "owner"), role("2", "admin")]), null);
  assert.equal(rolePickerCapNotice(100, page(99)), null);
  assert.equal(rolePickerCapNotice(0, []), null);
});

test("a short page discloses itself with the RolesSection wording", () => {
  // 105 roles in the workspace, 100 of them fetched: the offer stops at the
  // page minus the owner the pickers filter out.
  assert.equal(rolePickerCapNotice(105, page(99)), "Showing 99 of 104 roles.");
});