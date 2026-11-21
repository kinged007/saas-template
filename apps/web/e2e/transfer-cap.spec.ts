import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * The "New owner" picker on workspace settings offers one page of members, and
 * the endpoint caps the page. Past that cap the notice says how much is missing,
 * and it has to be the accessible description of the trigger it annotates.
 */

const CAP = "Showing 95 of 138 members.";

const member = (i: number, over: Record<string, unknown> = {}) => ({
  id: `user-${i}`,
  email: `member${i}@example.com`,
  display_name: `Member ${i}`,
  first_name: "Member",
  last_name: String(i),
  membership_id: `mem-${i}`,
  role_id: "2",
  role: "admin",
  status: "active",
  joined_at: "2026-01-01T00:00:00Z",
  ...over,
});

/**
 * A full page: an owner, a legacy `Owner`, two suspended, an invite, the rest
 * active non-owners. The legacy row and the invite are both rejected by
 * transferEligibleMembers, for different reasons.
 */
const PAGE_ROWS = [
  member(0, { role: "owner" }),
  member(100, { role: "Owner", email: "legacy-owner@example.com" }),
  member(1, { status: "suspended" }),
  member(2, { status: "suspended" }),
  member(101, { status: "invited", email: "invited@example.com" }),
  ...Array.from({ length: 95 }, (_, i) => member(i + 3)),
];

const memberList = (page: Page, total: number) =>
  page.route(
    (url) => url.pathname.endsWith("/api/v1/members"),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "x-total-count": String(total) },
        body: JSON.stringify(PAGE_ROWS),
      }),
  );

// single_workspace hides the whole danger zone, so the transfer block needs it off.
const signIn = (page: Page) =>
  mockApi(page, { signedIn: true, identity: { ...IDENTITY, single_workspace: false } });

const trigger = (page: Page) => page.getByRole("combobox", { name: "New owner" });

test.describe("transfer cap notice", () => {
  test("a capped workspace discloses the missing tail", async ({ page }) => {
    await signIn(page);
    await memberList(page, 143);
    await page.goto("/settings/workspace/general");

    await expect(page.getByText(CAP)).toBeVisible();
    await expect(trigger(page)).toHaveAccessibleDescription(CAP);
    // The picker offers the eligible members, which is what the notice counts.
    await trigger(page).click();
    await expect(page.getByRole("option")).toHaveCount(95);
    // A workspace created before the case-insensitive API check can hold
    // `Owner` beside `owner`; offering it produces a 409 on transfer. An invite
    // is not an active member, so it is refused too.
    await expect(page.getByRole("option", { name: /legacy-owner@example\.com/ })).toHaveCount(0);
    await expect(page.getByRole("option", { name: /invited@example\.com/ })).toHaveCount(0);
  });

  test("an uncapped workspace leaves no dangling description", async ({ page }) => {
    await signIn(page);
    await memberList(page, 100);
    await page.goto("/settings/workspace/general");

    await expect(trigger(page)).toBeVisible();
    expect(await trigger(page).getAttribute("aria-describedby")).toBeNull();
    await expect(page.getByText("Showing")).toHaveCount(0);
  });
});
