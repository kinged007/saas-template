import { expect } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/** The OAuth callback page's terminal states must offer a way back to /login. */
test.describe("oauth callback escape", () => {
  test("missing code shows a link back to sign-in", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.goto("/oauth/callback");

    await expect(page.getByText("Missing sign-in code.")).toBeVisible();
    const link = page.getByRole("link", { name: "Back to sign-in" });
    await expect(link).toBeVisible();
    await link.click();
    await page.waitForURL(/\/login$/);
  });

  test("an error code shows a link that carries the error through to /login", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.goto("/oauth/callback?error=invalid%20or%20expired%20state");

    await expect(page.getByText("Sign-in failed.")).toBeVisible();
    await page.getByRole("link", { name: "Back to sign-in" }).click();
    await page.waitForURL(/\/login\?error=/);
    // LoginPage renders the carried error back into the same message.
    await expect(page.getByText("Sign-in failed.")).toBeVisible();
  });

  test("the callback page keeps rendering while the identity settles", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    // Later handlers win over mockApi's catch-all: the /auth/me that
    // exchangeOAuthCode sends after the token lands never answers, so the
    // identity stays unsettled — exactly the window where the workspace gate
    // used to return null and unmount this page mid-exchange.
    await page.route("**/api/v1/auth/me", () => new Promise<void>(() => {}));

    await page.goto("/oauth/callback?code=code-123");
    // The token lands within milliseconds and (before the lift) the gate
    // blanks the page at that moment, so the pending state has to be checked
    // after that window, not during it.
    await page.waitForTimeout(2_000);
    await expect(page.getByText("Signing you in…")).toBeVisible();
  });

  test("a pending callback falls back to the escape once the timeout elapses", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    // Later handlers win over mockApi's catch-all: the exchange never answers,
    // so the page stays pending and only the timeout can end that state.
    await page.route("**/api/v1/auth/oauth/token", () => new Promise<void>(() => {}));
    // runFor drives the page's own clock, so OAUTH_CALLBACK_TIMEOUT_MS crosses
    // here without paying 15s of wall clock in CI.
    await page.clock.install();

    await page.goto("/oauth/callback?code=code-123");

    await expect(page.getByText("Signing you in…")).toBeVisible();
    // The escape belongs to the terminal states, so a pending page with a live
    // exchange shows nothing — asserting it now keeps the fallback honest.
    await expect(page.getByRole("link", { name: "Back to sign-in" })).toHaveCount(0);

    await page.clock.runFor(15_000);

    await expect(page.getByText("Sign-in is taking longer than expected.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to sign-in" })).toBeVisible();
  });
});
