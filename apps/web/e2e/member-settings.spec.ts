import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * Guard behaviour of the member settings layout (UserSettingsLayout). Every API
 * call is mocked, so these run against the dev server with no backend.
 */

/** Asserts on the pathname, so a redirect may add a query string. */
const path = (page: Page) => expect.poll(() => new URL(page.url()).pathname);

/**
 * The delegated read for `user-9`, a member other than the signed-in
 * `IDENTITY` (`user-1`) — a target equal to your own id redirects instead of
 * editing. `mockApi` has no slot for it, as that answers list calls.
 */
async function mockTargetProfile(page: Page) {
  await page.route("**/api/v1/users/user-9/profile", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ first_name: "Target", last_name: "Member" }),
    })
  );
}

/**
 * Records whether the access-denied panel was ever rendered, since the whole
 * point of the loading gate is a flash that resolves before the first
 * assertion could see it.
 */
async function watchForDenial(page: Page) {
  await page.addInitScript(() => {
    const flag = (window as unknown as { __denied: string[] });
    flag.__denied = [];
    // `document` rather than `document.documentElement`: the init script runs
    // before the document element exists.
    new MutationObserver(() => {
      if (document.body?.textContent?.includes("Access denied")) flag.__denied.push(location.href);
    }).observe(document, { childList: true, subtree: true, characterData: true });
  });
}

test.describe("member settings layout", () => {
  test("a cold load never flashes Access denied at a permitted caller", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await mockTargetProfile(page);
    // Registered after mockApi, so it wins; fallback() hands on to the mock.
    await page.route("**/api/v1/auth/me", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.fallback();
    });
    await watchForDenial(page);

    await page.goto("/users/user-9/settings/general");
    await expect(page.getByText("Member Settings")).toBeVisible();
    expect(await page.evaluate(() => (window as unknown as { __denied: string[] }).__denied)).toEqual(
      []
    );
  });

  test("a cold load does not render the editor for your own id before redirecting", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.route("**/api/v1/auth/me", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.fallback();
    });
    await watchForDenial(page);

    await page.goto("/users/user-1/settings/security");
    await path(page).toBe("/settings/profile/security");
    expect(await page.evaluate(() => (window as unknown as { __denied: string[] }).__denied)).toEqual(
      []
    );
  });

  test("your own id redirects to the matching self tab", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/users/user-1/settings/security");
    await path(page).toBe("/settings/profile/security");
  });

  test("a caller without profile:update is refused", async ({ page }) => {
    await mockApi(page, {
      signedIn: true,
      identity: { ...IDENTITY, is_superuser: false, permissions: [] },
    });
    await page.goto("/users/user-3/settings/general");
    await expect(page.getByText("Access denied")).toBeVisible();
  });

  test("the settings nav is named after the page heading", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await mockTargetProfile(page);
    await page.goto("/users/user-9/settings/general");

    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toBeVisible();
    const headingName = (await heading.textContent())?.trim() ?? "";
    expect(headingName).not.toBe("");

    // `exact` is what pins it: Playwright's default name match is substring,
    // under which the old default label "Settings" also matched "Member
    // Settings" and the assertion passed either way.
    const settingsNav = page.getByRole("navigation", { name: headingName, exact: true });
    await expect(settingsNav).toBeVisible();
    await expect(settingsNav.getByRole("link", { name: "General" })).toBeVisible();
  });
});
