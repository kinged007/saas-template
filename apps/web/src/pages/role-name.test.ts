import assert from "node:assert/strict";
import { test } from "node:test";

import { isManagerRoleName, isOwnerRoleName } from "./role-name.ts";

// A workspace created before the case-insensitive name check (#328) can hold a
// row named `Owner` beside its seeded `owner`, and that row is the owner role to
// the API. The UI has to make the same call, or it offers controls the API
// refuses with 409 and hides controls it would allow.
test("the owner role is the row whose name is \"owner\" in any case", () => {
  for (const name of ["owner", "Owner", "OWNER", "oWnEr"]) {
    assert.equal(isOwnerRoleName(name), true, name);
  }
  for (const name of ["admin", "owners", "owner ", "", null, undefined]) {
    assert.equal(isOwnerRoleName(name), false, String(name));
  }
});

test("a manager is an owner or an admin, both in any case", () => {
  for (const name of ["owner", "Owner", "admin", "Admin", "ADMIN"]) {
    assert.equal(isManagerRoleName(name), true, name);
  }
  for (const name of ["editor", "viewer", "admins", "", null, undefined]) {
    assert.equal(isManagerRoleName(name), false, String(name));
  }
});
