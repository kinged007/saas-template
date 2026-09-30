import { expect, test } from "playwright/test";

// Regression check for #370 against the real stack (scripts/dev.py + the real
// API), no mocks: the refresh cookie used to be rejected cross-origin on the
// 127.0.0.1 alias, which killed the session and sent every signed-in route
// back to /login. Seeded demo credentials, see src/seed.py DEMO_PASSWORD.
const EMAIL = "admin@example.com";
const PASSWORD = "password";

test("a session survives the refresh call and a hard navigation", async ({ page }) => {
  const refreshStatuses: number[] = [];
  page.on("response", (r) => {
    if (new URL(r.url()).pathname === "/api/v1/auth/refresh") {
      refreshStatuses.push(r.status());
    }
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login/);

  // A hard navigation drops the in-memory access token (#274) and has to
  // recover it from the refresh cookie — the call require_csrf gates. A
  // rejected refresh bounces to /login, so idle first, then read the calls.
  await page.goto("/settings/profile/general");
  await page.waitForTimeout(3000);
  console.log(`final url: ${page.url()} | refresh: ${JSON.stringify(refreshStatuses)}`);

  await expect(page).toHaveURL(/\/settings\/profile\/general/);
  expect(refreshStatuses).toContain(200);
  expect(refreshStatuses).not.toContain(403);
});
