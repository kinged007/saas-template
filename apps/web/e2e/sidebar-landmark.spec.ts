import { expect } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * Both navigation landmarks must carry a name, and must stay distinguishable
 * on the settings pages, where the shell sidebar sits next to the settings
 * nav of the page itself.
 */

test.describe("sidebar landmark", () => {
  test("the shell sidebar is a named navigation landmark holding links and group headings", async ({
    page,
  }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/members");
    await expect(page.getByRole("heading", { name: "Members", exact: true })).toBeVisible();

    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav).toBeVisible();
    await expect(nav.getByRole("link", { name: "Dashboard" })).toBeVisible();
    // The group heading belongs to the navigation, not to the page outline.
    await expect(nav.getByRole("heading", { name: "Demo" })).toBeVisible();
  });

  test("a settings page names both landmarks it renders", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/settings/profile/general");

    // Asserted as a pair: naming only one of the two leaves the other
    // nameless, which is the regression this guards.
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    const settingsNav = page.getByRole("navigation", { name: "Settings" });
    await expect(settingsNav).toBeVisible();
    await expect(settingsNav.getByRole("link", { name: "General" })).toBeVisible();
  });
});
