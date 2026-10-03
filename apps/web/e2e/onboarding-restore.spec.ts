import { expect, type Locator, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

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

    // By role, not by text: the focus move only announces a heading if the
    // title is one, and a plain div matches the text query. The level is
    // pinned because h3 is the level the card's place in the page outline
    // depends on, and a name-only query also matches h2 or h4.
    const heading = page.getByRole("heading", { name: "Get set up", level: 3 });
    await expect(heading).toHaveCount(1);
    await expect(heading).toBeVisible();
    await expect(heading).toHaveAccessibleName("Get set up");
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
