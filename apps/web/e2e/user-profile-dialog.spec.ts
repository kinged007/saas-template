import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The profile dialog on the members page reads `usePublicProfile`, a plain
 * react-query against `/users/:id/profile` under the app-wide 5xx fail-fast
 * policy: a refused load lands in the dialog's error branch with no cached
 * rows and no retry budget behind it. With `refetchOnWindowFocus` off, the
 * dialog's Try again is the only recovery that does not involve closing the
 * dialog or reloading the page. The InboxPage avatar opens the same dialog
 * component, so the affordance added to ProfileBody covers both consumers.
 */

const MEMBER = {
  id: "user-7",
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

const PROFILE = {
  id: "user-7",
  email: "member@example.com",
  first_name: "Member",
  last_name: "One",
  display_name: "Member",
  bio: "Building things",
  location: "Berlin",
};

const PROFILE_ROUTE = "**/api/v1/users/user-7/profile";

/** Open the dialog with the profile route already answered — the dialog fires the request on open. */
async function openMembersProfile(page: Page, profile: (route: import("playwright/test").Route) => void) {
  await mockApi(page, { signedIn: true });
  await page.route(
    (url) => url.pathname.endsWith("/api/v1/members"),
    (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([MEMBER]) }),
  );
  await page.route(PROFILE_ROUTE, profile);
  await page.goto("/members");
  await page.getByRole("button", { name: "Open profile for Member" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
}

test.describe("user profile dialog", () => {
  test("a 500 renders the failure with Try again, and Try again recovers", async ({ page }) => {
    let calls = 0;
    let succeed = false;
    await openMembersProfile(page, (route) => {
      calls += 1;
      return route.fulfill({
        status: succeed ? 200 : 500,
        contentType: "application/json",
        body: succeed ? JSON.stringify(PROFILE) : JSON.stringify({ detail: "Boom" }),
      });
    });

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Could not load profile.")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Try again" })).toBeVisible();

    const before = calls;
    succeed = true;
    await dialog.getByRole("button", { name: "Try again" }).click();
    // The recovered dialog renders the profile fields — the click re-ran the
    // query, it did not merely dismiss the failure text.
    await expect(dialog.getByText("Building things")).toBeVisible();
    await expect(dialog.getByText("member@example.com")).toBeVisible();
    await expect(dialog.getByText("Could not load profile.")).toHaveCount(0);
    expect(calls).toBeGreaterThan(before);
  });
});
