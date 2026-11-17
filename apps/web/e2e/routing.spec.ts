import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * Regression tests for the router redirects in src/App.tsx. Every API call is
 * mocked, so these run against the dev server with no backend or database.
 */

/** Asserts on the pathname, so a redirect may add a query string. */
const path = (page: Page) => expect.poll(() => new URL(page.url()).pathname);

// A redirect that lands correctly and then throws would still pass a URL-only
// assertion, so every spec also fails on an uncaught page error.

test.describe("routing", () => {
  test("signed-out visitor on an unknown URL lands on the login page", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.goto("/no-such-page");
    await path(page).toBe("/login");
  });

  test("signed-in user on an unknown URL sees the not-found page", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/no-such-page");
    await path(page).toBe("/no-such-page");
    await expect(page.getByText("Page not found")).toBeVisible();
  });

  test("signed-in user on /login is redirected to the dashboard", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/login");
    await path(page).toBe("/");
  });

  test("signed-in user on /register is redirected to the dashboard", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/register");
    await path(page).toBe("/");
  });

  test("signed-out visitor on /register sees the register page", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.goto("/register");
    await path(page).toBe("/register");
    await expect(page.getByRole("button", { name: "Register" })).toBeVisible();
  });

  for (const [what, url, expected] of [
    ["an unknown profile settings tab", "/settings/profile/nope", "/settings/profile/general"],
    ["an unknown workspace settings tab", "/settings/workspace/nope", "/settings/workspace/general"],
    ["the profile settings index", "/settings/profile", "/settings/profile/general"],
    ["the workspace settings index", "/settings/workspace", "/settings/workspace/general"],
    ["the legacy /roles URL", "/roles", "/settings/workspace/roles"],
    ["the legacy /jobs URL", "/jobs", "/settings/workspace/jobs"],
  ] as const) {
    test(`${what} redirects to ${expected}`, async ({ page }) => {
      await mockApi(page, { signedIn: true });
      await page.goto(url);
      await path(page).toBe(expected);
    });
  }
});
