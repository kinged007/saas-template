import { expect, test, type Page } from "playwright/test";

/**
 * Regression tests for the router redirects in src/App.tsx. Every API call is
 * mocked, so these run against the dev server with no backend or database.
 */

const IDENTITY = {
  id: "user-1",
  email: "e2e@example.com",
  first_name: "E2E",
  last_name: "User",
  is_superuser: true,
  permissions: ["*"],
  workspaces: [{ id: "ws-1", name: "Acme Corp", role: "owner" }],
  single_workspace: true,
};

const ACCESS_TOKEN = [
  btoa(JSON.stringify({ alg: "HS256", typ: "JWT" })),
  btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600, sub: "user-1" })),
  "sig",
].join(".");

/**
 * Fulfill every backend call so the app runs with no API process. The session
 * endpoints decide auth; the list endpoints must answer with a bare array
 * (@refinedev/simple-rest maps the body straight to `data`); `/auth/config`
 * must report registration_enabled, or RegisterPage bounces to /login.
 */
async function mockApi(page: Page, { signedIn }: { signedIn: boolean }) {
  await page.route("**/api/v1/**", async (route) => {
    const reply = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    const { pathname } = new URL(route.request().url());
    if (pathname.endsWith("/auth/refresh")) {
      if (!signedIn) return reply(401, { detail: "No refresh token" });
      return reply(200, { access_token: ACCESS_TOKEN, token_type: "bearer" });
    }
    if (pathname.endsWith("/auth/me")) {
      if (!signedIn) return reply(401, { detail: "Not authenticated" });
      return reply(200, IDENTITY);
    }
    if (pathname.endsWith("/auth/config")) {
      return reply(200, {
        registration_enabled: true,
        password_enabled: true,
        oauth_enabled: false,
        providers: [],
      });
    }
    if (pathname.endsWith("/auth/logout")) return route.fulfill({ status: 204, body: "" });
    return reply(200, []);
  });
  // The auth check only refreshes when the signed-in marker is set, so seed it
  // before any app code runs.
  await page.addInitScript(
    ({ hasSession }) => window.localStorage.setItem("tf_has_session", hasSession ? "1" : "0"),
    { hasSession: signedIn },
  );
}

test.describe("routing", () => {
  test("signed-out visitor on an unknown URL lands on the login page", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.goto("/no-such-page");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("signed-in user on an unknown URL sees the not-found page", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/no-such-page");
    await expect(page).toHaveURL(/\/no-such-page$/);
    await expect(page.getByText("Page not found")).toBeVisible();
  });

  test("signed-in user on /register is redirected to the dashboard", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/register");
    await expect.poll(() => new URL(page.url()).pathname).toBe("/");
  });

  test("signed-out visitor on /register sees the register page", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.goto("/register");
    await expect(page).toHaveURL(/\/register$/);
    await expect(page.getByRole("button", { name: "Register" })).toBeVisible();
  });

  for (const [what, url, expected] of [
    ["unknown profile settings tab", "/settings/profile/nope", "/settings/profile/general"],
    ["unknown workspace settings tab", "/settings/workspace/nope", "/settings/workspace/general"],
    ["profile settings index", "/settings/profile", "/settings/profile/general"],
    ["workspace settings index", "/settings/workspace", "/settings/workspace/general"],
  ] as const) {
    test(`${what} falls back to the section index`, async ({ page }) => {
      await mockApi(page, { signedIn: true });
      await page.goto(url);
      await expect(page).toHaveURL(new RegExp(`${expected}$`));
    });
  }
});
