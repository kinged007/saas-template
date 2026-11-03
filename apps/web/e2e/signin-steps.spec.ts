import { expect } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The sign-in form is stepped: email first, then password on Continue, with
 * OAuth providers behind a "Sign in another way" toggle. Every API call is
 * mocked, so no backend (and no DATABASE_URL) is needed.
 */
test.describe("sign-in steps", () => {
  test("email continues to the password step and back", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.goto("/login");

    const email = page.getByLabel("Email");
    const password = page.getByLabel("Password");
    await expect(password).toBeHidden();
    await email.fill("e2e@example.com");
    await page.getByRole("button", { name: "Continue", exact: true }).click();

    await expect(password).toBeVisible();
    await expect(page.getByText("Signing in as")).toBeVisible();
    await expect(email).toBeHidden();

    await page.getByRole("button", { name: "Change" }).click();
    await expect(email).toBeVisible();
    await expect(password).toBeHidden();
  });

  test("another way reveals the OAuth providers", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    // Registered after mockApi, so it takes precedence over its catch-all.
    await page.route("**/api/v1/auth/config", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          registration_enabled: true,
          password_enabled: true,
          oauth_enabled: true,
          providers: [{ id: "testidp", display_name: "Test IdP" }],
        }),
      }),
    );
    await page.goto("/login");

    const toggle = page.getByRole("button", { name: "Sign in another way" });
    await expect(toggle).toBeVisible();
    await expect(page.getByRole("button", { name: "Continue with Test IdP" })).toBeHidden();

    await toggle.click();
    await expect(page.getByRole("button", { name: "Continue with Test IdP" })).toBeVisible();

    await page.getByRole("button", { name: "Back to email sign-in" }).click();
    await expect(page.getByRole("button", { name: "Continue with Test IdP" })).toBeHidden();
  });

  test("no providers means no another-way toggle", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.goto("/login");

    await expect(page.getByRole("button", { name: "Sign in another way" })).toBeHidden();
  });

  test("a mapped domain jumps straight to its provider", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    // Registered after mockApi, so they take precedence over its catch-all.
    await page.route("**/api/v1/auth/config", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          registration_enabled: true,
          password_enabled: true,
          oauth_enabled: true,
          providers: [{ id: "testidp", display_name: "Test IdP" }],
        }),
      }),
    );
    await page.route("**/api/v1/auth/sign-in/method", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ provider: "testidp" }),
      }),
    );
    await page.goto("/login");

    await page.getByLabel("Email").fill("newhire@corp.example");
    await page.getByRole("button", { name: "Continue", exact: true }).click();

    // A real redirect leaves the SPA for the provider's authorize URL.
    await page.waitForURL(/\/api\/v1\/auth\/oauth\/testidp\/authorize/);
  });

  test("an unmapped domain falls through to the password step", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.route("**/api/v1/auth/config", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          registration_enabled: true,
          password_enabled: true,
          oauth_enabled: true,
          providers: [{ id: "testidp", display_name: "Test IdP" }],
        }),
      }),
    );
    await page.route("**/api/v1/auth/sign-in/method", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ provider: null }),
      }),
    );
    await page.goto("/login");

    await page.getByLabel("Email").fill("someone@example.com");
    await page.getByRole("button", { name: "Continue", exact: true }).click();

    await expect(page.getByLabel("Password")).toBeVisible();
  });
});
