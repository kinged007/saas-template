import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * Forgot-password error copy lives in src/pages/forgot-password.ts and is
 * rendered by ForgotPasswordPage's catch fallback. These specs pin what the
 * user actually sees for a 429 (with and without Retry-After) and a plain
 * 500, so page and helper cannot drift on the shared strings.
 *
 * Registered after `mockApi` on purpose — Playwright runs the most recently
 * added matching handler first, so only this URL is intercepted.
 */
const submit = async (page: Page) => {
  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill("e2e@example.com");
  await page.getByRole("button", { name: "Send reset link" }).click();
};

test.describe("forgot-password error messages", () => {
  test("429 with Retry-After shows the wait message", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.route("**/auth/forgot-password", (route) =>
      route.fulfill({
        status: 429,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Too many attempts" }),
        headers: { "retry-after": "95" },
      }),
    );
    await submit(page);
    await expect(page.getByText("Too many attempts — try again in ~2 min.")).toBeVisible();
  });

  test("429 without a usable Retry-After shows the later message", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.route("**/auth/forgot-password", (route) =>
      route.fulfill({ status: 429, contentType: "application/json", body: "{}" }),
    );
    await submit(page);
    await expect(page.getByText("Too many attempts — try again later.")).toBeVisible();
  });

  test("500 shows the generic request-failed message", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.route("**/auth/forgot-password", (route) =>
      route.fulfill({ status: 500, contentType: "application/json", body: "{}" }),
    );
    await submit(page);
    await expect(page.getByText("request failed", { exact: true })).toBeVisible();
  });
});
