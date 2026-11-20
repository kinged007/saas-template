import { expect } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * Regression tests for the workspace Danger zone (GeneralSection). Every API
 * call is mocked, so these run against the dev server with no backend.
 */

const identity = {
  ...IDENTITY,
  // The Danger zone never renders on a single-workspace account.
  single_workspace: false,
};

// One active non-owner: the transfer block only renders its picker when a
// transfer candidate exists, and the members mock answers with a bare array.
const ADA = {
  id: "user-2",
  email: "ada@example.com",
  display_name: "Ada Lovelace",
  first_name: "Ada",
  last_name: "Lovelace",
  membership_id: "mem-2",
  role_id: "role-admin",
  role: "admin",
  status: "active",
};

test("picking a new owner shows the pick in the trigger", async ({ page }) => {
  await mockApi(page, { signedIn: true, identity, lists: { members: [ADA] } });
  await page.goto("/settings/workspace/general");

  await expect(page.getByText("Danger zone")).toBeVisible();
  const trigger = page.getByRole("combobox", { name: "New owner" });
  // Placeholder until a member is picked; a SelectValue with no children
  // would keep showing it forever (PR #426).
  await expect(trigger).toHaveText("Select member");
  await trigger.click();
  await page.getByRole("option", { name: /Ada/ }).click();
  await expect(trigger).toHaveText(/Ada/);
});
