import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The role pickers on MembersPage drop the tail of a workspace whose role list
 * exceeds one page, and they say so with a notice. The notice has to be the
 * accessible description of the trigger it annotates, and it has to count the
 * list the dropdown offers.
 */

const role = (id: string, name: string) => ({
  id,
  workspace_id: "ws-1",
  name,
  permissions: [],
  system: false,
});

const CAP = "Showing 99 of 104 roles.";

const MEMBER = {
  id: "user-2",
  email: "member@example.com",
  display_name: "Member",
  first_name: "Member",
  last_name: "One",
  membership_id: "mem-1",
  role_id: "2",
  role: "admin",
  status: "active",
  joined_at: "2026-01-01T00:00:00Z",
};

/** The role list page: the owner first, then `rest` custom roles, `total` overall. */
const roles = (page: Page, { rest, total }: { rest: number; total: number }) =>
  page.route(
    (url) => url.pathname.endsWith("/api/v1/roles"),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "x-total-count": String(total) },
        body: JSON.stringify([
          role("1", "owner"),
          ...Array.from({ length: rest }, (_, i) => role(String(i + 2), `role ${i}`)),
        ]),
      }),
  );

const members = (page: Page) =>
  page.route(
    (url) => url.pathname.endsWith("/api/v1/members"),
    (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([MEMBER]) }),
  );

const rowTrigger = (page: Page) =>
  page.getByRole("row").filter({ hasText: "member@example.com" }).getByRole("combobox");
const inviteTrigger = (page: Page) => page.getByRole("combobox").last();

test.describe("role cap notice", () => {
  test("both role triggers describe themselves with the cap", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await members(page);
    await roles(page, { rest: 99, total: 105 });
    await page.goto("/members");

    await expect(page.getByText(CAP)).toHaveCount(2);
    // The dropdown offers the page minus its owner, so the notice counts that,
    // not the raw page the endpoint returned.
    await expect(rowTrigger(page)).toHaveAccessibleDescription(CAP);
    await expect(inviteTrigger(page)).toHaveAccessibleDescription(CAP);
    // Two notices, so two ids: a shared one would annotate both pickers with
    // whichever paragraph came first.
    const [member, invite] = await Promise.all(
      [rowTrigger(page), inviteTrigger(page)].map((locator) => locator.getAttribute("aria-describedby")),
    );
    expect(member).toBeTruthy();
    expect(invite).toBeTruthy();
    expect(member).not.toBe(invite);

    await rowTrigger(page).click();
    await expect(page.getByRole("option")).toHaveCount(99);
  });

  test("an uncapped workspace leaves no dangling description", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await members(page);
    await roles(page, { rest: 3, total: 4 });
    await page.goto("/members");

    await expect(rowTrigger(page)).toBeVisible();
    expect(await rowTrigger(page).getAttribute("aria-describedby")).toBeNull();
    expect(await inviteTrigger(page).getAttribute("aria-describedby")).toBeNull();
    await expect(page.getByText("Showing")).toHaveCount(0);
  });
});