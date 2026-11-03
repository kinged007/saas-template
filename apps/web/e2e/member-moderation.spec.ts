import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * Member moderation lives on the member's settings page (Membership tab),
 * not on the members table: suspend, MFA reset and removal each confirm
 * first. Every API call is mocked, so no backend (and no DATABASE_URL) is
 * needed.
 */

const MEMBER = {
  id: "user-2",
  email: "member@example.com",
  display_name: "Member T.",
  first_name: "Member",
  last_name: "Two",
  avatar_url: null,
  membership_id: "mem-2",
  role_id: "2",
  role: "editor",
  status: "active",
  joined_at: "2026-01-01T00:00:00Z",
};

const members = (page: Page) =>
  page.route(
    (url) => url.pathname.endsWith("/api/v1/members"),
    (route) =>
      route.request().method() === "GET"
        ? route.fulfill({
            status: 200,
            contentType: "application/json",
            headers: { "x-total-count": "1" },
            body: JSON.stringify([MEMBER]),
          })
        : route.fallback(),
  );

const post = (page: Page, suffix: string, status = 200) =>
  page.route(
    (url) => url.pathname.endsWith(`/api/v1/members/mem-2/${suffix}`),
    (route) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify({}) }),
  );

test.describe("member moderation", () => {
  test("suspending confirms first, then toasts", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await members(page);
    await post(page, "suspend");
    await page.goto("/users/user-2/settings/membership");

    // The tab rendered with the member's moderation actions.
    await expect(page.getByRole("button", { name: "Suspend", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Suspend", exact: true }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Suspend Member T.?")).toBeVisible();
    await dialog.getByRole("button", { name: "Suspend", exact: true }).click();
    await expect(page.getByText("Member T. suspended")).toBeVisible();
  });

  test("resetting MFA confirms first, then toasts", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await members(page);
    await post(page, "reset-mfa");
    await page.goto("/users/user-2/settings/membership");

    await page.getByRole("button", { name: "Reset MFA", exact: true }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Reset MFA for Member T.?")).toBeVisible();
    await dialog.getByRole("button", { name: "Reset MFA", exact: true }).click();
    await expect(page.getByText("MFA reset for Member T.")).toBeVisible();
  });

  test("removing confirms first, then returns to the members list", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await members(page);
    await page.route(
      (url) => url.pathname.endsWith("/api/v1/members/mem-2"),
      (route) =>
        route.request().method() === "DELETE"
          ? route.fulfill({ status: 204, body: "" })
          : route.fallback(),
    );
    await page.goto("/users/user-2/settings/membership");

    await page.getByRole("button", { name: "Remove", exact: true }).click();

    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByText("Remove Member T. from this workspace?"),
    ).toBeVisible();
    await dialog.getByRole("button", { name: "Remove", exact: true }).click();
    await page.waitForURL(/\/members\??$/);
  });
});
