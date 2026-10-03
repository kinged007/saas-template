import assert from "node:assert/strict";
import { test } from "node:test";

import type { Role } from "@/types";
import { resolveInviteRole } from "./invite-role.ts";

const role = (over: Partial<Role> = {}): Role => ({
  id: "r-1",
  workspace_id: "w-1",
  name: "Admin",
  permissions: ["member:create"],
  system: true,
  ...over,
});

test("resolveInviteRole returns the picked role", () => {
  const admin = role({ id: "r-1" });
  const editor = role({ id: "r-2", name: "Editor" });
  assert.equal(resolveInviteRole([admin, editor], "r-2"), editor);
});

test("resolveInviteRole disarms when the id outlives the role list", () => {
  // The id survives a refetch, but the refetched list no longer names it: the
  // submit must stay blocked instead of sending a role the server dropped.
  const before = [role({ id: "r-1" }), role({ id: "r-2" })];
  const after = [role({ id: "r-2" })];
  assert.equal(resolveInviteRole(before, "r-1")?.id, "r-1");
  assert.equal(resolveInviteRole(after, "r-1"), undefined);
  assert.equal(resolveInviteRole([], "r-1"), undefined);
});

test("resolveInviteRole is disarmed before a selection is made", () => {
  assert.equal(resolveInviteRole([role()], ""), undefined);
});

test("resolveInviteRole only resolves ids the offered list names", () => {
  // The page hands over assignableRoles, which drops owner, so an owner id — one
  // the picker never offers — cannot arm the submit.
  const offered = [role({ id: "r-1" })];
  assert.equal(resolveInviteRole(offered, role({ id: "r-0", name: "owner" }).id), undefined);
});
