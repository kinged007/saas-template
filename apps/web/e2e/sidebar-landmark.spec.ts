import { expect, test as base } from "playwright/test";

import { mockApi } from "./mock-api";

/**
 * The sidebar shell must be a navigation landmark. The settings pages already
 * render their own `nav`, so the shell one needs a name to be told apart.
 */
const test = base.extend<{ pageerrors: Error[] }>({
  pageerrors: [
    async ({ page }, use) => {
      const errors: Error[] = [];
      page.on("pageerror", (error) => errors.push(error));
      await use(errors);
      expect(errors).toEqual([]);
    },
    { auto: true },
  ],
});

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
});
