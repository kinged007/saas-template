import assert from "node:assert/strict";
import { test } from "node:test";

import {
  adminWorkspacePatch,
  asAdminWorkspaceDetail,
  type AdminWorkspaceDetail,
} from "./workspaces-form.ts";

const detail = (over: Partial<AdminWorkspaceDetail> = {}): AdminWorkspaceDetail => ({
  id: "w-1",
  name: "Acme",
  slug: "acme",
  description: null,
  member_count: 1,
  members: [
    { id: "u-1", email: "a@example.com", display_name: "A", role: "owner", is_active: true },
  ],
  ...over,
});

test("asAdminWorkspaceDetail accepts a full payload and rejects broken ones", () => {
  assert.ok(asAdminWorkspaceDetail(detail()));
  assert.equal(asAdminWorkspaceDetail({ ...detail(), name: undefined }), undefined);
  assert.equal(asAdminWorkspaceDetail({ ...detail(), slug: "" }), undefined);
  assert.equal(asAdminWorkspaceDetail({ ...detail(), members: undefined }), undefined);
  assert.equal(asAdminWorkspaceDetail({ id: "", members: [] }), undefined);
  assert.equal(asAdminWorkspaceDetail(null), undefined);
});

test("adminWorkspacePatch sends only changed keys", () => {
  const patch = adminWorkspacePatch(detail(), { name: "Acme", slug: "acme", description: "" });
  assert.deepEqual(patch.values, {});
  assert.equal(patch.url, "admin/workspaces/w-1");
  assert.equal(patch.method, "patch");
  assert.equal(patch.errorNotification, false);

  const renamed = adminWorkspacePatch(detail(), { name: "Acme Inc", slug: "acme", description: "" });
  assert.deepEqual(renamed.values, { name: "Acme Inc" });

  const described = adminWorkspacePatch(detail(), {
    name: "Acme",
    slug: "acme",
    description: "New blurb",
  });
  assert.deepEqual(described.values, { description: "New blurb" });
});

test("adminWorkspacePatch leaves an untouched null description out of the payload", () => {
  const patch = adminWorkspacePatch(detail({ description: null }), {
    name: "Acme",
    slug: "acme",
    description: "",
  });
  assert.ok(!("description" in patch.values));

  const cleared = adminWorkspacePatch(detail({ description: "Old" }), {
    name: "Acme",
    slug: "acme",
    description: "",
  });
  assert.deepEqual(cleared.values, { description: "" });
});
