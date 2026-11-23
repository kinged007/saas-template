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

  test("Link is an action, not a toggle, so it reports no pressed state", async ({ page }) => {
    const toolbar = await openToolbar(page);
    const link = toolbar.getByRole("button", { name: "Link", exact: true });

    // The seven toggles above all carry aria-pressed. Link opens an editor, so
    // it must not claim a state it does not maintain.
    await expect(link).not.toHaveAttribute("aria-pressed", /.+/);
  });

  test("Link edits the URL in a popover, not a native prompt", async ({ page }) => {
    const toolbar = await openToolbar(page);
    const editor = page.getByRole("dialog").locator('[contenteditable="true"]');

    // A native prompt blocks the main thread and some screen readers drop it,
    // so the editor has to be a surface in the page.
    await page.evaluate(() => {
      const w = window as unknown as { __prompted: boolean };
      w.__prompted = false;
      window.prompt = () => {
        w.__prompted = true;
        return "https://from-prompt.example.com";
      };
    });
    await editor.click();
    await page.keyboard.type("hello");
    await page.keyboard.press("ControlOrMeta+a");
    await toolbar.getByRole("button", { name: "Link", exact: true }).click();

    const url = page.getByRole("textbox", { name: "Link URL" });
    // Radix renders the popover as a role="dialog" with no name of its own, and
    // it is the element a screen reader enters first.
    const linkDialog = page.getByRole("dialog", { name: "Link URL" });
    await expect(linkDialog).toBeVisible();
    await expect(url).toBeVisible();
    expect(await page.evaluate(() => (window as unknown as { __prompted: boolean }).__prompted)).toBe(false);

    // The compose dialog has its own "Cancel", so every popover button is
    // looked up inside the popover rather than by name across the page.
    const apply = linkDialog.getByRole("button", { name: "Apply", exact: true });
    const cancel = linkDialog.getByRole("button", { name: "Cancel", exact: true });
    const remove = linkDialog.getByRole("button", { name: "Remove link", exact: true });

    await url.fill("https://example.com/docs");
    // Enter has to submit the form, the way the prompt's OK button did, so a
    // keyboard user never has to reach for Apply. The click path is covered by
    // the two steps below.
    await url.press("Enter");
    await expect(editor.locator('a[href="https://example.com/docs"]')).toHaveText("hello");
    // Typing has to continue in the document, not in the dismissed form.
    await expect(editor).toBeFocused();

    await page.keyboard.press("ControlOrMeta+a");
    await toolbar.getByRole("button", { name: "Link", exact: true }).click();
    await expect(url).toHaveValue("https://example.com/docs");

    // An emptied field is a no-op, not a malformed URL to complain about.
    await url.fill("");
    await apply.click();
    await expect(linkDialog).toHaveCount(0);

    // Anything that is not an absolute http(s) URL is refused, rather than
    // reaching the document as an href.
    await page.keyboard.press("ControlOrMeta+a");
    await toolbar.getByRole("button", { name: "Link", exact: true }).click();
    await url.fill("javascript:alert(1)");
    await apply.click();
    await expect(page.getByText("Enter an absolute http:// or https:// URL.")).toBeVisible();
    expect(await page.evaluate(() => (window as unknown as { __prompted: boolean }).__prompted)).toBe(false);

    // Backing out leaves the existing href alone and hands focus back.
    await cancel.click();
    await expect(linkDialog).toHaveCount(0);
    await expect(editor.locator('a[href="https://example.com/docs"]')).toHaveCount(1);
    await expect(editor).toBeFocused();

    // The popover still holds the link, so the removal control is there.
    await toolbar.getByRole("button", { name: "Link", exact: true }).click();
    await remove.click();
    await expect(editor.locator("a")).toHaveCount(0);
  });

  test("dismissing the popover leaves focus where the interaction ended", async ({ page }) => {
    const toolbar = await openToolbar(page);
    const editor = page.getByRole("dialog").locator('[contenteditable="true"]');
    const link = toolbar.getByRole("button", { name: "Link", exact: true });
    const linkDialog = page.getByRole("dialog", { name: "Link URL" });

    await editor.click();
    await page.keyboard.type("hello");
    await link.click();
    await expect(linkDialog).toBeVisible();

    // The trigger toggles the popover shut, which is one of its own exits: the
    // caret goes back to the document being edited.
    await link.click();
    await expect(linkDialog).toHaveCount(0);
    await expect(editor).toBeFocused();

    await link.click();
    await expect(linkDialog).toBeVisible();

    // A click elsewhere in the compose dialog dismisses the popover, and that
    // click owns the focus afterwards: the caret must not jump back into the
    // document the user clicked away from.
    await page.getByRole("dialog", { name: "New conversation" }).getByRole("heading").click();
    await expect(linkDialog).toHaveCount(0);
    await expect(editor).not.toBeFocused();

    // Escape is Radix's own exit, the one path it owns end to end: the caret
    // goes back to the document being edited, like Cancel.
    await link.click();
    await expect(linkDialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(linkDialog).toHaveCount(0);
    await expect(editor).toBeFocused();
  });

  test("a bare host typed in the text still autolinks", async ({ page }) => {
    await openToolbar(page);
    const editor = page.getByRole("dialog").locator('[contenteditable="true"]');

    // The editor's href allow-list must not cost the composer autolinking:
    // `www.example.com ` is stored as `http://www.example.com/`, never as the
    // relative href the bare text would otherwise be.
    await editor.click();
    await page.keyboard.type("www.example.com ");
    await expect(editor.locator('a[href^="http://www.example.com"]')).toHaveText("www.example.com");

    // A protocol-relative value is not a host, so it is still refused.
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.type("//evil.example.com ");
    await expect(editor.locator("a")).toHaveCount(0);
  });

  test("a host that hides its real target behind userinfo is not autolinked", async ({ page }) => {
    await openToolbar(page);
    const editor = page.getByRole("dialog").locator('[contenteditable="true"]');

    // `http://evil.example.com@attacker.com` is a valid URL whose host is
    // `attacker.com`, so matching `evil.example.com` on its own would turn a
    // deceptive link into an anchor. It has to stay plain text.
    await editor.click();
    await page.keyboard.type("evil.example.com@attacker.com ");
    await expect(editor.locator("a")).toHaveCount(0);
    await expect(editor).toHaveText(/evil\.example\.com@attacker\.com/);
  });

  test("a pasted anchor keeps its mark when its href is safe as written", async ({ page }) => {
    await openToolbar(page);
    const editor = page.getByRole("dialog").locator('[contenteditable="true"]');

    // `isAllowedUri` is what the extension runs on `parseHTML` as well, so a
    // gate that only knows absolute http(s) hrefs unlinks a whole page pasted
    // from a browser. The unsafe hrefs in the same paste are still dropped.
    await editor.click();
    await editor.evaluate((node) => {
      const html =
        '<p><a href="/inbox">inbox</a> <a href="mailto:a@example.com">mail</a> ' +
        '<a href="javascript:alert(1)">script</a> <a href="//evil.example.com">evil</a></p>';
      const data = new DataTransfer();
      data.setData("text/html", html);
      node.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
    });

    await expect(editor.locator('a[href="/inbox"]')).toHaveText("inbox");
    await expect(editor.locator('a[href="mailto:a@example.com"]')).toHaveText("mail");
    // The two refused hrefs are plain text, so nothing points at another host.
    await expect(editor.locator("a")).toHaveCount(2);
    await expect(editor).toHaveText(/script evil/);
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
