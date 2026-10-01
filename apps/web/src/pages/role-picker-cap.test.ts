import assert from "node:assert/strict";
import { test } from "node:test";

import { assignableRoles, rolePickerCapNotice } from "./role-picker-cap.ts";
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

/** A full picker page holding no owner row, so `count` custom roles and no owner. */
const pageWithoutOwner = (count: number): Role[] =>
  Array.from({ length: count }, (_, i) => role(String(i + 1), `r${i}`));

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
  // Same page without an owner row: nothing is filtered, so the offer is the
  // whole page and the denominator is the untouched workspace total.
  assert.equal(rolePickerCapNotice(105, pageWithoutOwner(100)), "Showing 100 of 105 roles.");
});

// The backend calls the owner role the row whose lower-cased name is "owner"
// (is_owner_role_name) and ranks on func.lower(Role.name), so a row spelled
// `Owner` is the locked owner role to the API. The pickers must not offer it.
test("the owner role is matched case-insensitively, like the backend", () => {
  const names = assignableRoles([role("1", "owner"), role("2", "Owner"), role("3", "admin")]).map(
    (r) => r.name,
  );
  assert.deepEqual(names, ["admin"]);
  // A case-variant owner row is the owner to the count too: it is excluded from
  // the offer and from the pickable total, matching the offer and notice to the
  // same list.
  assert.equal(
    rolePickerCapNotice(105, [role("1", "Owner"), ...pageWithoutOwner(99)]),
    "Showing 99 of 104 roles.",
  );
});

// A missing `X-Total-Count` makes the total 0, so the denominator is clamped at
// 0 rather than going negative and the notice stays suppressed.
test("no notice when the workspace total is missing", () => {
  assert.equal(rolePickerCapNotice(0, page(99)), null);
});