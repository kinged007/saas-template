import { expect, test as base } from "playwright/test";
import { mockApi } from "./mock-api";

/**
 * Every composer toolbar button is an icon-only control, so each one has to
 * carry the `title` + `aria-label` pair — `title` paints the hover tooltip,
 * `aria-label` is what a screen reader announces. The editor renders the
 * toolbar as a `role="toolbar"` named "Formatting", so these assertions never
 * depend on a Tailwind class or a DOM position.
 */
const EXPECTED = [
  "Bold",
  "Italic",
  "Inline code",
  "Code block",
  "Bullet list",
  "Ordered list",
  "Quote",
  "Link",
];

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

test.describe("composer toolbar", () => {
  test("every button is reachable by role and accessible name", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/inbox");
    await page.getByRole("button", { name: "Compose", exact: true }).click();

    const toolbar = page
      .getByRole("dialog")
      .getByRole("toolbar", { name: "Formatting" });
    await expect(toolbar).toBeVisible();

    for (const name of EXPECTED) {
      await expect(toolbar.getByRole("button", { name, exact: true })).toHaveCount(1);
    }
  });

  test("every button carries both title and aria-label", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/inbox");
    await page.getByRole("button", { name: "Compose", exact: true }).click();

    const toolbar = page
      .getByRole("dialog")
      .getByRole("toolbar", { name: "Formatting" });
    await expect(toolbar).toBeVisible();

    // `title` alone would satisfy the name lookup above, so assert the
    // attributes themselves: that is the fix this spec guards.
    await expect(toolbar.locator("button:not([aria-label])")).toHaveCount(0);
    await expect(toolbar.locator("button:not([title])")).toHaveCount(0);
  });
});
