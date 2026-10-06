import { expect, type Locator, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The dashboard's card titles are `h3` sections of the page `h2`, so the whole
 * outline inside `<main>` is asserted as one list: naming the headings that do
 * exist passes just as well with a card left out, which is the regression.
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
        "H2: Acme Corp",
        "H3: Get set up",
        "H3: Members",
        "H3: Inbox",
      ]);

    // By role, not by text: a text query matches the div CardTitle renders.
    await expect(
      pageBody(page).getByRole("heading", { name: "Members", level: 3 }),
    ).toBeVisible();
    await expect(
      pageBody(page).getByRole("heading", { name: "Inbox", level: 3 }),
    ).toBeVisible();
  });
});
