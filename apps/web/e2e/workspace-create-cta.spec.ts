import { expect } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * With SINGLE_WORKSPACE on and the auto-join failed, /auth/me reports
 * single_workspace: true and no workspaces. /workspaces/create redirects home in
 * that mode, so a create affordance is a control that navigates nowhere.
 */
const lockedOut = { ...IDENTITY, single_workspace: true, workspaces: [] };

test.describe("workspace create call to action", () => {
  test("single-workspace mode offers no way to create one", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: lockedOut });
    await page.goto("/");

    await expect(page.getByText("You're not a member of any workspace yet.")).toBeVisible();
    // Sidebar empty state (button) and the dashboard "No workspace yet" card
    // (link wrapped around a button) are both affordances for the same route.
    await expect(page.getByRole("button", { name: "Create workspace" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Create workspace" })).toHaveCount(0);
  });

  test("the button is still there when a workspace can be created", async ({ page }) => {
    await mockApi(page, {
      signedIn: true,
      identity: { ...IDENTITY, single_workspace: false, workspaces: [] },
    });
    await page.goto("/");

    // The sidebar button and the dashboard link both render; .first() picks the
    // sidebar one out of the two matching buttons.
    await expect(page.getByRole("button", { name: "Create workspace" }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Create workspace" })).toBeVisible();
  });
});
