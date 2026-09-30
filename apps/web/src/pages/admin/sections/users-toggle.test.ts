import assert from "node:assert/strict";
import { test } from "node:test";

import type { AdminUser } from "@/types";
import {
  adminUserPatch,
  asAdminUserDetail,
  canToggleUser,
  errorMessage,
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

test("asAdminUserDetail rejects a workspaces payload with no usable id", () => {
  const { id: _dropped, ...noId } = detail();
  assert.equal(asAdminUserDetail({ ...noId, workspaces: [] }), undefined);
  assert.equal(asAdminUserDetail({ ...detail(), id: 42 }), undefined);
});

test("pageRange clamps the visible window and never reports zero pages", () => {
  assert.deepEqual(pageRange(1, 0), { from: 0, to: 0, totalPages: 1 });
  assert.deepEqual(pageRange(1, 25), { from: 1, to: 20, totalPages: 2 });
  assert.deepEqual(pageRange(2, 25), { from: 21, to: 25, totalPages: 2 });
  assert.deepEqual(pageRange(1, 40), { from: 1, to: 20, totalPages: 2 });
  assert.deepEqual(pageRange(1, 41), { from: 1, to: 20, totalPages: 3 });
  // A page that empties out after a refetch must not invert the range.
  assert.deepEqual(pageRange(3, 5), { from: 5, to: 5, totalPages: 1 });
  // A current page below 1 must not report a negative start.
  assert.deepEqual(pageRange(0, 10), { from: 1, to: 0, totalPages: 1 });
});

test("errorMessage renders the detail instead of [object Object]", () => {
  assert.equal(
    errorMessage({ message: "You cannot disable your own account" }),
    "You cannot disable your own account",
  );
  assert.equal(
    errorMessage({ response: { data: { detail: { code: "2fa_required" } } } }),
    '{"code":"2fa_required"}',
  );
  assert.equal(errorMessage({}), "Request failed");
  assert.equal(errorMessage(null), "Request failed");
});

test("adminUserPatch's url is built from a row typed as the list item, not the detail", () => {
  const row: AdminUser = { ...detail(), workspaces: undefined };
  assert.equal(adminUserPatch(row, false).url, "admin/users/u-1");
});
