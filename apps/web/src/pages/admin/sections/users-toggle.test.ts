import assert from "node:assert/strict";
import { test } from "node:test";

import type { AdminUser } from "@/types";
import {
  adminUserPatch,
  asAdminUserDetail,
  canToggleUser,
  pageRange,
  type AdminUserDetail,
} from "./users-toggle.ts";

const detail = (over: Partial<AdminUserDetail> = {}): AdminUserDetail => ({
  id: "u-1",
  email: "a@example.com",
  display_name: "A",
  is_active: true,
  is_superuser: false,
  workspaces: [{ id: "w-1", name: "W", slug: "w", role: "owner" }],
  ...over,
});

test("adminUserPatch targets the user and inverts is_active with a matching toast", () => {
  assert.deepEqual(adminUserPatch(detail(), false), {
    url: "admin/users/u-1",
    method: "patch",
    values: { is_active: false },
    successNotification: { message: "Account disabled", type: "success" },
    errorNotification: false,
  });

  const reEnable = adminUserPatch(detail({ is_active: false }), true);
  assert.deepEqual(reEnable.values, { is_active: true });
  assert.equal(reEnable.successNotification.message, "Account re-enabled");
});

test("canToggleUser hides the toggle on the viewer's own account", () => {
  assert.equal(canToggleUser(detail(), "u-1"), false);
  assert.equal(canToggleUser(detail(), "someone-else"), true);
  assert.equal(canToggleUser(detail(), null), true);
  assert.equal(canToggleUser(detail(), undefined), true);
});

test("asAdminUserDetail rejects a payload without a workspaces array", () => {
  const { workspaces: _dropped, ...noWorkspaces } = detail();
  assert.equal(asAdminUserDetail(noWorkspaces), undefined);
  assert.equal(asAdminUserDetail(null), undefined);
  assert.equal(asAdminUserDetail(undefined), undefined);
  assert.deepEqual(asAdminUserDetail(detail()), detail());
});

test("pageRange clamps the visible window and never reports zero pages", () => {
  assert.deepEqual(pageRange(1, 0), { from: 0, to: 0, totalPages: 1 });
  assert.deepEqual(pageRange(1, 25), { from: 1, to: 20, totalPages: 2 });
  assert.deepEqual(pageRange(2, 25), { from: 21, to: 25, totalPages: 2 });
  assert.deepEqual(pageRange(1, 40), { from: 1, to: 20, totalPages: 2 });
  assert.deepEqual(pageRange(1, 41), { from: 1, to: 20, totalPages: 3 });
});

test("an untyped patch payload still satisfies the list item type", () => {
  const row: AdminUser = { ...detail(), workspaces: undefined };
  assert.equal(adminUserPatch(row, false).url, "admin/users/u-1");
});
