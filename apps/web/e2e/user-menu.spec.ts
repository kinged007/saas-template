import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * The user menu hides the Workspace Settings entry under SINGLE_WORKSPACE. The
 * flag rides /auth/me, so the mocked identity decides; the entry stays gated on
 * the role when the flag is off.
 */
const openUserMenu = async (page: Page) => {
  await page.getByRole("button", { name: /e2e@example\.com/ }).click();
  // Positive control first: a closed Radix menu renders no items at all, so
  // asserting a count of 0 before the menu is open would pass either way.
  await expect(page.getByRole("menuitem", { name: "Profile Settings" })).toBeVisible();
};

const workspaceSettings = (page: Page) =>
  page.getByRole("menuitem", { name: "Workspace Settings" });

test.describe("user menu", () => {
  test("the workspace settings entry is hidden under SINGLE_WORKSPACE", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: { ...IDENTITY, single_workspace: true } });
    await page.goto("/");
    await openUserMenu(page);

    await expect(workspaceSettings(page)).toHaveCount(0);
  });

  test("the workspace settings entry stays for a workspace owner otherwise", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: { ...IDENTITY, single_workspace: false } });
    await page.goto("/");
    await openUserMenu(page);

    await expect(workspaceSettings(page)).toBeVisible();
  });

  test("a non-admin never sees the workspace settings entry", async ({ page }) => {
    await mockApi(page, {
      signedIn: true,
      identity: {
        ...IDENTITY,
        is_superuser: false,
        permissions: [],
        workspaces: [{ id: "ws-1", name: "Acme Corp", slug: "acme-corp", role: "viewer" }],
      },
    });
    await page.goto("/");
    await openUserMenu(page);

    await expect(workspaceSettings(page)).toHaveCount(0);
  });
});
