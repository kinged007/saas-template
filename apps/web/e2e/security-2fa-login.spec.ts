import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { ACCESS_TOKEN, mockApiTwoFactor } from "./mock-api";

/**
 * The password + 2FA login challenge round trip: a 2FA-enabled user signs in,
 * is challenged, submits a code, and lands authenticated. A wrong code is
 * refused without losing the challenge, so the retry reuses the same token.
 *
 * Every API call is mocked, so no backend (and no DATABASE_URL) is needed.
 * mockApiTwoFactor answers the password POST with a `2fa_required` challenge;
 * the wrong-code test overrides only `/auth/2fa/login` after it (the most
 * recently added matching handler wins) to refuse one code and accept the
 * next, while keeping the challenge token fixed like the API does.
 */
const path = (page: Page) => expect.poll(() => new URL(page.url()).pathname);

const signIn = async (page: Page) => {
  await page.getByLabel("Email").fill("e2e@example.com");
  await page.getByLabel("Password").fill("Passw0rd!23");
  await page.getByRole("button", { name: "Sign in" }).click();
};

test.describe("2FA login challenge", () => {
  test("a valid code lands authenticated", async ({ page }) => {
    await mockApiTwoFactor(page, { signedIn: false });
    await page.goto("/login");

    await signIn(page);

    // The password POST challenges instead of signing in.
    await expect(page.getByLabel("Two-factor code")).toBeVisible();
    await page.getByLabel("Two-factor code").fill("123456");
    await page.getByRole("button", { name: "Verify" }).click();

    // Authenticated: the app leaves /login and renders the signed-in identity.
    await path(page).toBe("/");
    await expect(page.getByRole("button", { name: /e2e@example\.com/ })).toBeVisible();
  });

  test("a wrong code is refused without losing the challenge", async ({ page }) => {
    const api = await mockApiTwoFactor(page, { signedIn: false });
    const attempts: { code: string; challenge_token: string }[] = [];
    // Registered after mockApiTwoFactor, so it takes precedence over its
    // accept-any-code handler for this URL.
    await page.route("**/api/v1/auth/2fa/login", async (route) => {
      const body = route.request().postDataJSON() as {
        challenge_token: string;
        code: string;
      };
      attempts.push(body);
      if (body.code !== "123456") {
        return route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({ detail: "invalid code" }),
        });
      }
      api.signIn();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ access_token: ACCESS_TOKEN, token_type: "bearer" }),
      });
    });
    await page.goto("/login");

    await signIn(page);
    await expect(page.getByLabel("Two-factor code")).toBeVisible();

    await page.getByLabel("Two-factor code").fill("000000");
    await page.getByRole("button", { name: "Verify" }).click();

    // Refused, but the code form stays: the challenge was not lost.
    await expect(page.getByText("Verification failed. Try again.")).toBeVisible();
    await expect(page.getByLabel("Two-factor code")).toBeVisible();

    await page.getByLabel("Two-factor code").fill("123456");
    await page.getByRole("button", { name: "Verify" }).click();

    await path(page).toBe("/");
    await expect(page.getByRole("button", { name: /e2e@example\.com/ })).toBeVisible();
    // The retry reused the challenge from the password POST — no fresh
    // password sign-in was needed to recover.
    expect(attempts).toHaveLength(2);
    expect(attempts[0].challenge_token).toBe("e2e-challenge");
    expect(attempts[1].challenge_token).toBe("e2e-challenge");
  });
});
