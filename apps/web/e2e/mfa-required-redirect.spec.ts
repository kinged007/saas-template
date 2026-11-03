import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The backend MFA gate refuses workspace data with 403 "mfa required for
 * this workspace". The app bounces those failures to the enrollment page
 * with the reason as a toast. Every API call is mocked, so no backend (and
 * no DATABASE_URL) is needed.
 */
function mfaForbidden(page: Page) {
  return page.route(
    (url) => url.pathname.endsWith("/api/v1/members"),
    (route) =>
      route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "mfa required for this workspace" }),
      }),
  );
}

test.describe("mfa required redirect", () => {
  test("an MFA 403 bounces to the security page with a notice", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    // Registered after mockApi, so it takes precedence over its catch-all.
    await mfaForbidden(page);
    // The bounce is a hard redirect that aborts the goto's own navigation,
    // so poll for the landing instead of awaiting it.
    await page.goto("/members").catch(() => {});
    await expect.poll(() => new URL(page.url()).pathname).toBe("/settings/profile/security");
    await expect(page.getByText("mfa required for this workspace")).toBeVisible();
  });

  test("repeated enforcement never reloads the security page", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await mfaForbidden(page);
    await page.goto("/members").catch(() => {});
    await expect.poll(() => new URL(page.url()).pathname).toBe("/settings/profile/security");

    // Hitting another gated page from the security page bounces straight
    // back. The guard must not reload while already there.
    await page.goto("/members").catch(() => {});
    await expect.poll(() => new URL(page.url()).pathname).toBe("/settings/profile/security");
    await page.waitForTimeout(1500);
    expect(new URL(page.url()).pathname).toBe("/settings/profile/security");
    await expect(page.getByText("mfa required for this workspace")).toBeVisible();
  });
});
