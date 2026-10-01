import { expect, test as base, type Locator, type Page } from "playwright/test";

import { mockApi } from "./mock-api";

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

/** Dashboard with the card already dismissed, so restoring is the only way back. */
async function dismissedOnboarding(page: Page): Promise<Locator> {
  await mockApi(page, { signedIn: true });
  await page.addInitScript(() =>
    window.localStorage.setItem("tf_onboarding_dismissed:user-1:ws-1", "1"),
  );
  await page.goto("/");
  const restore = page.getByRole("button", { name: "Show setup checklist again" });
  await expect(restore).toBeVisible();
  return restore;
}

test.describe("onboarding restore", () => {
  test("keyboard restore moves focus to the heading and paints no ring on it", async ({ page }) => {
    const restore = await dismissedOnboarding(page);

    await restore.focus();
    await page.keyboard.press("Enter");

    const heading = page.getByText("Get set up", { exact: true });
    await expect(heading).toBeVisible();
    // The focus move is what tells a screen reader the card is back, so it has
    // to survive the styling fix.
    await expect(heading).toBeFocused();
    // Tailwind's `outline-none` is a transparent outline, not
    // `outline-style: none`, so the ring is gone when the color is clear.
    expect(await heading.evaluate((el) => getComputedStyle(el).outlineColor)).toBe(
      "rgba(0, 0, 0, 0)",
    );
  });
});
