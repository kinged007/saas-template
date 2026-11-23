import { expect, type Locator, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * The dashboard's card titles are `h2` sections of the page `h1`, so the whole
 * outline inside `<main>` is asserted as one list: naming the headings that do
 * exist passes just as well with a card left out, which is the regression.
 *
 * Both branches are pinned, because the no-workspace one returns before the
 * page title and once had an empty outline: its only title was a `CardTitle`,
 * which renders a div.
 */

/** The AppLayout `<main>` — the sidebar's `SidebarInset` `<main>` comes first. */
const pageBody = (page: Page) => page.locator("main").last();

const outline = (scope: Locator) =>
  scope
    .locator("h1, h2, h3, h4, h5, h6")
    .evaluateAll((els) =>
      els.map((el) => `${el.tagName}: ${el.textContent?.trim()}`),
    );

test.describe("dashboard card headings", () => {
  test("every dashboard card is a section of the page title", async ({
    page,
  }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/");

    // The onboarding card shows by default: the mocked `api-keys` and
    // `invitations` lists are empty, so no step is done.
    await expect
      .poll(() => outline(pageBody(page)))
      .toEqual([
        "H1: Acme Corp",
        "H2: Get set up",
        "H2: Members",
        "H2: Inbox",
      ]);

    // By role, not by text: a text query matches the div CardTitle renders.
    await expect(
      page.getByRole("heading", { name: "Acme Corp", level: 1 }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Members", level: 2 }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Inbox", level: 2 }),
    ).toBeVisible();
  });

  test("the no-workspace branch has an outline too", async ({ page }) => {
    await mockApi(page, {
      signedIn: true,
      identity: { ...IDENTITY, single_workspace: false, workspaces: [] },
    });
    await page.goto("/");

    await expect
      .poll(() => outline(pageBody(page)))
      .toEqual(["H1: No workspace yet"]);
  });
});
