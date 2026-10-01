import { expect, type Locator, type Page } from "playwright/test";
import { test } from "./fixtures";
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

test.describe("composer toolbar", () => {
  /** The compose dialog's formatting toolbar, opened from the inbox. */
  const openToolbar = async (page: Page): Promise<Locator> => {
    await mockApi(page, { signedIn: true });
    await page.goto("/inbox");
    await page.getByRole("button", { name: "Compose", exact: true }).click();
    const toolbar = page.getByRole("dialog").getByRole("toolbar", { name: "Formatting" });
    await expect(toolbar).toBeVisible();
    return toolbar;
  };

  test("every button is reachable by role and accessible name", async ({ page }) => {
    const toolbar = await openToolbar(page);

    for (const name of EXPECTED) {
      await expect(toolbar.getByRole("button", { name, exact: true })).toHaveCount(1);
    }
  });

  test("every button carries both title and aria-label", async ({ page }) => {
    const toolbar = await openToolbar(page);

    // `title` alone would satisfy the name lookup above, so assert the
    // attributes themselves: that is the fix this spec guards.
    await expect(toolbar.locator("button:not([aria-label])")).toHaveCount(0);
    await expect(toolbar.locator("button:not([title])")).toHaveCount(0);
  });

  test("a toggle applies from the keyboard and reports its state", async ({ page }) => {
    const toolbar = await openToolbar(page);
    const editor = page.getByRole("dialog").locator('[contenteditable="true"]');
    const bold = toolbar.getByRole("button", { name: "Bold", exact: true });

    await editor.click();
    await page.keyboard.type("hello");
    // A collapsed caret only stores the mark for the next keystroke, so select
    // the text the way a user would before asking for bold.
    await page.keyboard.press("ControlOrMeta+a");
    await bold.focus();
    await page.keyboard.press("Enter");

    await expect(editor.locator("strong")).toHaveText("hello");
    await expect(bold).toHaveAttribute("aria-pressed", "true");

    // `aria-pressed` is a toggle, not a one-way latch. The command hands focus
    // back to the editor, so come back to the control the way a keyboard user
    // would.
    await bold.focus();
    await page.keyboard.press("Enter");
    await expect(editor.locator("strong")).toHaveCount(0);
    await expect(bold).toHaveAttribute("aria-pressed", "false");
  });

  test("the toolbar is a single tab stop with arrow-key navigation", async ({ page }) => {
    const toolbar = await openToolbar(page);
    const buttons = toolbar.getByRole("button");

    // APG toolbar: one tab stop for the whole group, arrows move inside it.
    await expect(toolbar.locator('button[tabindex="0"]')).toHaveCount(1);
    await expect(toolbar.locator('button[tabindex="-1"]')).toHaveCount(EXPECTED.length - 1);

    await buttons.first().focus();
    await page.keyboard.press("ArrowRight");
    await expect(buttons.nth(1)).toBeFocused();
    // The tab stop follows focus, so the walked-over button becomes the tab stop.
    await expect(buttons.nth(1)).toHaveAttribute("tabindex", "0");
    await expect(toolbar.locator('button[tabindex="0"]')).toHaveCount(1);
    await page.keyboard.press("End");
    await expect(buttons.last()).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect(buttons.first()).toBeFocused();
    await page.keyboard.press("Home");
    await expect(buttons.first()).toBeFocused();
  });

  test("the tab stop is the last control that had focus", async ({ page }) => {
    const toolbar = await openToolbar(page);
    const buttons = toolbar.getByRole("button");

    await buttons.nth(3).focus();
    await expect(buttons.nth(3)).toHaveAttribute("tabindex", "0");
    // Leaving the group and re-entering must return to that control, not to the
    // first one — the tab stop is where focus was left.
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    await expect(buttons.nth(3)).toBeFocused();
    await expect(buttons.nth(3)).toHaveAttribute("tabindex", "0");
  });
});
