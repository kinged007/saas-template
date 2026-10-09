import { expect, type Locator, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The inbox panes are built from icon-only buttons, so each one has to carry
 * the `title` + `aria-label` pair #332 established in the composer toolbar:
 * `title` paints the hover tooltip, `aria-label` is what a screen reader
 * announces. A control with neither is announced as a bare "button".
 *
 * The accessible name is the invariant and `title` duplicates it, so a control
 * whose two attributes disagree announces one action and hovers another. Align
 * `title` up to the accessible name, never shorten `aria-label` to the tooltip
 * (WCAG 2.5.3, Label in Name). #702: the inbox keeps the native `title` rather
 * than a Radix `Tooltip` (a wrapper span and a portal per button), so the
 * assertion is against the rendered `title` attribute.
 */

const CONVERSATION = {
  id: "conv-1",
  workspace_id: "ws-1",
  title: "Release plan",
  created_by_user_id: "user-1",
  last_message_at: "2026-01-02T10:00:00Z",
  last_message_preview: "shipping Friday",
  unread_count: 0,
  is_archived: false,
  participants: [],
  created_at: "2026-01-01T09:00:00Z",
  updated_at: "2026-01-02T10:00:00Z",
};

/** The AppLayout `<main>` — the sidebar's `SidebarInset` `<main>` comes first. */
const pageBody = (page: Page) => page.locator("main").last();

/**
 * The visible buttons in `scope`. A `display:none` button is outside the
 * accessibility tree, so it can neither be reached nor announced.
 */
async function visibleButtons(scope: Locator) {
  const found: Locator[] = [];
  for (const button of await scope.locator("button").all()) {
    if (await button.isVisible()) found.push(button);
  }
  return found;
}

/** The visible buttons in `scope`, waiting for the pane to mount. */
async function mountedButtons(scope: Locator) {
  await expect
    .poll(() => visibleButtons(scope).then((buttons) => buttons.length), {
      message: "the pane under audit never rendered a button",
    })
    .toBeGreaterThan(0);
  return visibleButtons(scope);
}

/**
 * A node line that carries an accessible name: `- button "Search":` for a name
 * computed from aria-label / title / text, or `- combobox: Active` for a Radix
 * trigger named by its value. An unnamed control prints a bare `- button:`.
 */
const NAMED = /^-\s[\w-]+(?:\s+"[^"]+"|:.*\S)/;

/**
 * Every visible button in `scope` carries an accessible name, read from the
 * accessibility snapshot rather than the JSX so a button named by its own text
 * passes without an aria-label; and every icon-only one carries both
 * `title` and `aria-label`, equal to each other.
 */
async function expectButtonsNamed(scope: Locator) {
  const iconOnly: Locator[] = [];
  for (const button of await mountedButtons(scope)) {
    const node = (await button.ariaSnapshot()).split("\n")[0];
    expect(node, "button without an accessible name").toMatch(NAMED);
    if ((await button.innerText()).trim() === "") iconOnly.push(button);
  }
  expect(iconOnly.length, "no icon-only button rendered — the scope under audit moved").toBeGreaterThan(0);
  for (const button of iconOnly) {
    await expect(button).toHaveAttribute("title", /\S/);
    await expect(button).toHaveAttribute("aria-label", /\S/);
    expect(
      await button.getAttribute("title"),
      "title and aria-label disagree — align title to the accessible name",
    ).toBe(await button.getAttribute("aria-label"));
  }
}

/**
 * The pane toggle names its own action — "Collapse panel" / "Expand panel" —
 * so its glyph has to follow `leftCollapsed`: a collapsed pane that announces
 * "Expand panel" while painting `PanelLeftClose` shows one action and says
 * another. The collapsed pane is `md:hidden` at the viewport this spec runs at,
 * so the toggle leaves the accessibility tree while staying mounted, and is
 * read with `includeHidden` to reach that state. #897.
 */
async function expectToggleIconTracksName(scope: Locator) {
  const toggle = scope.getByRole("button", { name: /^(Expand|Collapse) panel$/, includeHidden: true });
  await expect(toggle.locator("svg")).toHaveClass(/\blucide-panel-left-close\b/);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-label", "Expand panel");
  await expect(toggle.locator("svg")).toHaveClass(/\blucide-panel-left-open\b/);
}

test.describe("inbox icon buttons", () => {
  test("every icon-only button in the list pane is named", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/inbox");
    await expect(page.getByRole("button", { name: "Compose", exact: true })).toBeVisible();

    await expectButtonsNamed(pageBody(page));
  });

  test("every icon-only button in the thread header is named", async ({ page }) => {
    await mockApi(page, { signedIn: true, lists: { conversations: [CONVERSATION] } });
    await page.goto("/inbox");
    await page.getByRole("button", { name: /Release plan/ }).click();
    await expect(page.getByRole("heading", { name: "Release plan" })).toBeVisible();

    // The header is the ancestor of the conversation title that also holds the
    // participants row, so the scope covers the title actions and the
    // recipients action without naming a Tailwind class.
    const header = page.getByRole("heading", { name: "Release plan" }).locator("xpath=../../..");
    await expectButtonsNamed(header);
    await expect(header.getByRole("button", { name: "Edit title", exact: true })).toBeVisible();
  });

  test("every icon-only button in the notifications pane is named", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/inbox");
    // `exact` pins this tab: the header bell opens the same list under the
    // name "Show notifications", which a case-insensitive non-exact query
    // would match too.
    await pageBody(page).getByRole("button", { name: "Notifications", exact: true }).click();

    await expectButtonsNamed(pageBody(page));
  });

  test("the header bell announces its action, not a bare noun", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/inbox");
    // The bell sits in the AppLayout header, outside the panes audited above,
    // so its name is pinned here: a bare noun is announced as a single stray
    // word, the name has to state the action like every other control.
    await expect(page.getByRole("button", { name: "Show notifications", exact: true })).toBeVisible();
  });

  test("the messages pane toggle paints the icon it announces", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/inbox");
    await expect(page.getByRole("button", { name: "Compose", exact: true })).toBeVisible();

    await expectToggleIconTracksName(pageBody(page));
  });

  test("the notifications pane toggle paints the icon it announces", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/inbox");
    await pageBody(page).getByRole("button", { name: "Notifications", exact: true }).click();

    await expectToggleIconTracksName(pageBody(page));
  });
});
