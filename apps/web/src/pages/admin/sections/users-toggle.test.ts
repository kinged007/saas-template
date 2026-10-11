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

test("asAdminUserDetail rejects a workspaces payload with no usable id", () => {
  const { id: _dropped, ...noId } = detail();
  assert.equal(asAdminUserDetail({ ...noId, workspaces: [] }), undefined);
  assert.equal(asAdminUserDetail({ ...detail(), id: 42 }), undefined);
  assert.equal(asAdminUserDetail({ ...detail(), id: "" }), undefined);
});

test("asAdminUserDetail validates every AdminUserDetail field, not just id and workspaces", () => {
  const { email: _droppedEmail, ...noEmail } = detail();
  assert.equal(asAdminUserDetail(noEmail), undefined);
  const { display_name: _droppedName, ...noName } = detail();
  assert.equal(asAdminUserDetail(noName), undefined);
  const { is_active: _droppedActive, ...noActive } = detail();
  assert.equal(asAdminUserDetail(noActive), undefined);
  const { is_superuser: _droppedSuper, ...noSuper } = detail();
  assert.equal(asAdminUserDetail(noSuper), undefined);
});

test("asAdminUserDetail accepts a null created_at, which iso_or_none can serialize", () => {
  const nullDate = detail({ created_at: null });
  assert.deepEqual(asAdminUserDetail(nullDate), nullDate);
});

test("asAdminUserDetail accepts an optional created_at only when it is a string or null", () => {
  const withDate = detail({ created_at: "2024-01-01T00:00:00Z" });
  const withNoDate = detail({ created_at: undefined });
  assert.equal(asAdminUserDetail(withDate), withDate);
  assert.equal(asAdminUserDetail(withNoDate), withNoDate);
  const { created_at: _droppedDate, ...badDate } = detail();
  assert.equal(asAdminUserDetail({ ...badDate, created_at: 42 as unknown as string }), undefined);
});

test("asAdminUserDetail rejects a wrong type for the other guarded fields", () => {
  assert.equal(asAdminUserDetail({ ...detail(), email: 42 as unknown as string }), undefined);
  assert.equal(
    asAdminUserDetail({ ...detail(), display_name: 42 as unknown as string }),
    undefined,
  );
  assert.equal(asAdminUserDetail({ ...detail(), is_active: "yes" as unknown as boolean }), undefined);
  assert.equal(
    asAdminUserDetail({ ...detail(), is_superuser: "yes" as unknown as boolean }),
    undefined,
  );
});

test("pageRange clamps the visible window and never reports zero pages", () => {
  assert.deepEqual(pageRange(1, 0), { from: 0, to: 0, totalPages: 1 });
  assert.deepEqual(pageRange(1, 25), { from: 1, to: 20, totalPages: 2 });
  assert.deepEqual(pageRange(2, 25), { from: 21, to: 25, totalPages: 2 });
  assert.deepEqual(pageRange(1, 40), { from: 1, to: 20, totalPages: 2 });
  assert.deepEqual(pageRange(1, 41), { from: 1, to: 20, totalPages: 3 });
  // A page that empties out after a refetch must not invert the range.
  assert.deepEqual(pageRange(3, 5), { from: 5, to: 5, totalPages: 1 });
  // A current page below 1 must not report a negative start or invert the range.
  assert.deepEqual(pageRange(0, 10), { from: 1, to: 10, totalPages: 1 });
});

test("adminUserPatch's url is built from a row typed as the list item, not the detail", () => {
  const row: AdminUser = { ...detail(), workspaces: undefined };
  assert.equal(adminUserPatch(row, false).url, "admin/users/u-1");
});
