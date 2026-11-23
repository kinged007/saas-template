import { expect } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The mock used to answer every list with the whole fixture and no
 * `x-total-count`, so no spec could reach the capped role list the MembersPage
 * pickers disclose with a notice. It now answers the requested `_start`/`_end`
 * window with the fixture length as the total, like the backend's capped pages —
 * so a 105-role seed alone pages to 100 rows with total 105.
 */

const role = (id: string, name: string) => ({
  id,
  workspace_id: "ws-1",
  name,
  permissions: [],
  system: false,
});

// A workspace past the role cap: the owner role, then 104 custom roles.
const roles = [
  role("1", "owner"),
  ...Array.from({ length: 104 }, (_, i) => role(String(i + 2), `role ${i}`)),
];

const member = {
  id: "user-2",
  email: "member@example.com",
  display_name: "Member",
  first_name: "Member",
  last_name: "One",
  membership_id: "mem-1",
  role_id: "2",
  role: "admin",
  status: "active",
  joined_at: "2026-01-01T00:00:00Z",
};

test("a 105-role workspace discloses the cap at both pickers", async ({ page }) => {
  await mockApi(page, { signedIn: true, lists: { roles, members: [member] } });
  await page.goto("/members");

  // The default identity is a superuser, so both permission gates hold: the row
  // picker and the invite picker each carry the notice the mock's first page
  // (100 rows) and total (105) produce.
  await expect(page.locator("#members-role-cap")).toHaveText("Showing 99 of 104 roles.");
  await expect(page.locator("#invite-role-cap")).toHaveText("Showing 99 of 104 roles.");
});
