import { expect } from "playwright/test";

import { mockApi, test } from "./harness";

/**
 * The sidebar shell must be a navigation landmark. The settings pages already
 * render their own `nav`, so the shell one needs a name to be told apart.
 */

test.describe("sidebar landmark", () => {
  test("the shell sidebar is a named navigation landmark holding links and group headings", async ({
    page,
    errors,
  }) => {
    await mockApi(page, { signedIn: true, errors });
    await page.goto("/members");
    await expect(page.getByRole("heading", { name: "Members", exact: true })).toBeVisible();

    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav).toBeVisible();
    await expect(nav.getByRole("link", { name: "Dashboard" })).toBeVisible();
    // The group heading belongs to the navigation, not to the page outline.
    await expect(nav.getByRole("heading", { name: "Demo" })).toBeVisible();
  });
});
