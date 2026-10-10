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

    // Collapsed is where the flex hand-off matters: the nav now owns the column
    // the sidebar used to give the groups, so on the icon rail it has to stay
    // present with its links still reachable.
    await page.getByRole("button", { name: /toggle sidebar/i }).first().click();
    await expect(nav).toBeVisible();
    await expect(nav.getByRole("link", { name: "Dashboard" })).toBeVisible();
  });

  test("a short viewport keeps the landmark inside the scrolling sidebar", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 420 });
    await mockApi(page, { signedIn: true });
    await page.goto("/members");
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Dashboard" })).toBeVisible();

    // The groups do not fit, so the nav is the scroller: the flex hand-off
    // from SidebarContent is what keeps the overflow on the nav and not on
    // the page.
    const metrics = await nav.evaluate((el) => ({
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      bottom: el.getBoundingClientRect().bottom,
    }));
    expect(metrics.scrollHeight).toBeGreaterThan(metrics.clientHeight);
    expect(metrics.bottom).toBeLessThanOrEqual(420);
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
