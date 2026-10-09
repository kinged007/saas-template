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
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toBeVisible();
    const headingName = (await heading.textContent())?.trim() ?? "";

    // Asserted as a pair: naming only one of the two leaves the other
    // nameless, which is the regression this guards.
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    // The settings nav is named after the page heading, so it reads as part of
    // that page instead of a generic "Settings" landmark next to a
    // differently named heading. `exact` is what pins it: Playwright's default
    // name match is substring, under which "Settings" also matches
    // "Profile Settings" and the old assertion passed either way.
    const settingsNav = page.getByRole("navigation", { name: headingName, exact: true });
    await expect(settingsNav).toBeVisible();
    await expect(settingsNav.getByRole("link", { name: "General" })).toBeVisible();
  });
});
