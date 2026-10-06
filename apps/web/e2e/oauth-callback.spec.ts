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
});
