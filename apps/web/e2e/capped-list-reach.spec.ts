import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * Both lists that cap themselves in workspace settings have to leave a way past
 * the cap: the roles list pages through its own tail, and the transfer
 * disclosure names the members it drops, says which end of the list they are,
 * and links the list that holds them.
 */

const ROLES_ROUTE = "/settings/workspace/roles";
const GENERAL_ROUTE = "/settings/workspace/general";
const MEMBERS_ROUTE = "/members";

const role = (i: number) => ({
  id: String(i + 1),
  workspace_id: "ws-1",
  name: `role ${i}`,
  permissions: [],
  system: false,
});

const member = (i: number) => ({
  id: `user-${i}`,
  email: `member${i}@example.com`,
  display_name: `Member ${i}`,
  first_name: "Member",
  last_name: String(i),
  membership_id: `membership-${i}`,
  role_id: "2",
  role: "admin",
  status: "active",
  joined_at: "2026-01-01T00:00:00Z",
});

/** One page of `total` rows, sliced the way the endpoint slices them. */
const cappedPage = (url: string, total: number, rows: (i: number) => unknown) => {
  const params = new URL(url).searchParams;
  // simple-rest pages with `_start`/`_end`; the backend also reads the legacy
  // `offset`/`limit` pair, and `parse_query` prefers `_start` when both appear.
  const offset = Number(params.get("_start") ?? params.get("offset") ?? 0);
  const end = Number(params.get("_end") ?? 0);
  const limit = end
    ? end - offset
    : Number(params.get("limit") ?? params.get("_end") ?? 10);
  const all = Array.from({ length: total }, (_, i) => rows(i));
  return {
    status: 200,
    contentType: "application/json",
    headers: { "x-total-count": String(total) },
    body: JSON.stringify(all.slice(offset, offset + limit)),
  };
};

const roles = (page: Page, total: number) =>
  page.route(
    (url) => url.pathname.endsWith("/api/v1/roles"),
    (route) => route.fulfill(cappedPage(route.request().url(), total, role)),
  );

const catalog = (page: Page) =>
  page.route(
    (url) => url.pathname.endsWith("/api/v1/roles/permission-catalog"),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ catalog: ["role:read"], permissions: ["role:read"] }),
      }),
  );

const members = (page: Page, total: number) =>
  page.route(
    (url) => url.pathname.endsWith("/api/v1/members"),
    (route) => route.fulfill(cappedPage(route.request().url(), total, member)),
  );
// The transfer block sits in the danger zone, which only renders for a
// multi-workspace owner.
const owner = { ...IDENTITY, single_workspace: false };

const next = (page: Page) => page.getByRole("button", { name: "Next" });
const previous = (page: Page) => page.getByRole("button", { name: "Previous" });

test.describe("roles settings list", () => {
  test("pages past the cap and shows the rows the cap used to drop", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: owner });
    await roles(page, 104);
    await catalog(page);
    await page.goto(ROLES_ROUTE);

    // Page 1 says what it holds and that there is more, and offers the way to it.
    await expect(page.getByText("Showing 1–100 of 104")).toBeVisible();
    await expect(page.getByText("Page 1 of 2")).toBeVisible();
    await expect(page.getByText("role 99").first()).toBeVisible();
    await expect(page.getByText("role 100")).toHaveCount(0);

    await next(page).click();
    await expect(page.getByText("Page 2 of 2")).toBeVisible();
    await expect(page.getByText("Showing 101–104 of 104")).toBeVisible();
    await expect(page.getByText("role 100").first()).toBeVisible();

    await previous(page).click();
    await expect(page.getByText("Page 1 of 2")).toBeVisible();
    await expect(page.getByText("Showing 1–100 of 104")).toBeVisible();
  });

  test("a workspace inside one page carries no pager", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: owner });
    await roles(page, 4);
    await catalog(page);
    await page.goto(ROLES_ROUTE);

    // Anchors on the list itself: a page that never rendered rows could not
    // pass for a list that chose not to page.
    await expect(page.getByText("role 3").first()).toBeVisible();
    await expect(next(page)).toHaveCount(0);
    await expect(page.getByText("Showing")).toHaveCount(0);
  });
});

test.describe("transfer cap disclosure", () => {
  test("names the dropped members and links the list that holds them", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: owner });
    await members(page, 124);
    await page.goto(GENERAL_ROUTE);

    const notice = page.getByText("Showing the first 100 of 124 members");
    await expect(notice).toBeVisible();
    // members.py orders by created_at desc, so the rows this picker never sees
    // are the oldest: a count alone reads as an arbitrary subset.
    await expect(notice).toContainText("newest first");
    await expect(notice).toContainText("oldest members");

    const link = page.getByRole("link", { name: "See all members" });
    await expect(link).toHaveAttribute("href", MEMBERS_ROUTE);
    await link.click();
    await expect(page).toHaveURL(MEMBERS_ROUTE);
    // The destination pages through every candidate, cap and all.
    await expect(page.getByText("Showing 1–10 of 124")).toBeVisible();
    await expect(page.getByText("member10@example.com")).toHaveCount(0);
    await next(page).click();
    await expect(page.getByText("Showing 11–20 of 124")).toBeVisible();
    await expect(page.getByText("member10@example.com")).toBeVisible();
  });

  test("a workspace inside one page carries no disclosure", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: owner });
    await members(page, 3);
    await page.goto(GENERAL_ROUTE);

    // Anchors on the transfer block itself: a page that never rendered it
    // could not pass for a workspace that has no tail to disclose.
    await expect(page.getByRole("button", { name: "Transfer ownership" })).toBeVisible();
    await expect(page.getByRole("link", { name: "See all members" })).toHaveCount(0);
    await expect(page.getByText("Showing the first")).toHaveCount(0);
  });
});
