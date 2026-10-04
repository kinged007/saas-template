import { expect } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The setup-key copy button is icon-only and its icon flips to a check for 1.5 s
 * after the write, so the accessible name has to flip with it: a button that
 * still reads "Copy setup key" in the copied state announces the action the
 * user just performed instead of a confirmation. `title` duplicates the
 * accessible name (the pair #332 established), so the two are asserted equal.
 *
 * Registered after `mockApi` on purpose — Playwright runs the most recently
 * added matching handler first, so only this one URL is intercepted here.
 */
const SETUP = {
  setup_token: "setup-1",
  otpauth_uri: "otpauth://totp/Acme:E2E?secret=JBSWY3DPEHPK3PXP&issuer=Acme",
  secret: "JBSWY3DPEHPK3PXP",
};

test("the setup-key copy button announces the copy, then the confirmation", async ({ page }) => {
  // The handler awaits the clipboard write before it flips the icon, so a denied
  // write would fail the assertion below for the wrong reason.
  await page.context().grantPermissions(["clipboard-write"]);
  await mockApi(page, { signedIn: true });
  await page.route("**/api/v1/auth/2fa/setup", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(SETUP) }),
  );
  await page.goto("/settings/profile/security");
  await page.getByRole("button", { name: "Set up authenticator" }).click();

  const copy = page.getByRole("button", { name: "Copy setup key" });
  await expect(copy).toBeVisible();

  await copy.click();

  // Same button, new name: the query for "Copied" resolves only if the name
  // changed, so a stale label fails here instead of passing on the icon.
  const copied = page.getByRole("button", { name: "Copied", exact: true });
  await expect(copied).toBeVisible();
  await expect(copy).toHaveCount(0);
  // `title` duplicates the accessible name (the pair #332 established), so it
  // has to follow the same state.
  expect(await copied.getAttribute("title"), "title and aria-label disagree").toBe("Copied");
});
