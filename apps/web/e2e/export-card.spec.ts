import { expect, test as base, type Page } from "playwright/test";

/**
 * Regression tests for the workspace export card. Every API call is mocked, so
 * these run against the dev server with no backend or database.
 */

const pageerrors = async (page: Page) => {
  const errors: Error[] = [];
  page.on("pageerror", (error) => errors.push(error));
  return errors;
};

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

const RESOURCES_PATH = "/workspaces/export/resources";

/**
 * `resourcesFail` decides how GET /workspaces/export/resources answers, so a
 * test can put the card into the failed state and then recover it by flipping
 * the flag. Every aborted request is counted, which is how the no-auto-retry
 * and no-stacked-requests claims are checked.
 */
async function mockApi(page: Page, state: { resourcesFail: boolean; delayMs?: number; attempts: number[] }) {
  await page.route("**/api/v1/**", async (route) => {
    const reply = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    const { pathname } = new URL(route.request().url());
    if (pathname.endsWith("/auth/refresh")) {
      return reply(200, { access_token: ACCESS_TOKEN, token_type: "bearer" });
    }
    if (pathname.endsWith("/auth/me")) return reply(200, IDENTITY);
    if (pathname.endsWith("/auth/config")) {
      return reply(200, {
        registration_enabled: true,
        password_enabled: true,
        oauth_enabled: false,
        providers: [],
      });
    }
    if (pathname.endsWith(RESOURCES_PATH)) {
      state.attempts.push(Date.now());
      if (state.resourcesFail) return route.abort("failed");
      if (state.delayMs) await new Promise((r) => setTimeout(r, state.delayMs));
      return reply(200, { resources: ["members", "roles", "audit"] });
    }
    return reply(200, []);
  });
  await page.addInitScript(() => window.localStorage.setItem("tf_has_session", "1"));
}

const test = base.extend<{
  resources: { resourcesFail: boolean; delayMs?: number; attempts: number[] };
}>({
  resources: async ({}, use) => {
    await use({ resourcesFail: false, attempts: [] });
  },
});

const openSettings = async (
  page: Page,
  state: { resourcesFail: boolean; delayMs?: number; attempts: number[] },
) => {
  await mockApi(page, state);
  await page.goto("/settings/workspace/general");
  await expect(page.getByText("Data export")).toBeVisible();
};

test.describe("workspace export card", () => {
  test("the description promises no import and names what the JSON contains", async ({ page, resources }) => {
    const errors = await pageerrors(page);
    await openSettings(page, resources);

    const description = page.getByText(/Download a read-only snapshot of this workspace/);
    await expect(description).toBeVisible();
    // No import path exists in the API, so the copy must not offer one.
    const text = (await description.textContent()) ?? "";
    expect(text).not.toMatch(/importable|after import/i);
    await expect(description).toContainText("There is no import in this app");
    expect(errors).toEqual([]);
  });

  test("the description states the export caps, the truncated flag and the CSV prefix convention", async ({
    page,
    resources,
  }) => {
    const errors = await pageerrors(page);
    await openSettings(page, resources);

    const description = page.getByText(/Download a read-only snapshot of this workspace/);
    const text = (await description.textContent()) ?? "";
    // Three sections are capped, so the copy must name the cap and the flag
    // that reports it instead of implying the JSON is always complete.
    expect(text).toContain("5000");
    expect(text).toContain("truncated");
    // The apostrophe prefix is a convention a spreadsheet can drop, not a
    // guarantee, so the copy must not present it as one.
    expect(text).toMatch(/apostrophe/i);
    expect(text).toMatch(/convention|not a guarantee/i);
    expect(errors).toEqual([]);
  });

  test("a failed resources fetch offers a user-pressed retry and recovers", async ({ page, resources }) => {
    const errors = await pageerrors(page);
    resources.resourcesFail = true;
    await openSettings(page, resources);

    const alert = page.getByRole("alert");
    await expect(alert).toContainText("Could not load the exportable resources");
    const retry = page.getByRole("button", { name: "Retry" });
    await expect(retry).toBeVisible();
    await expect(page.getByRole("button", { name: "Export CSV" })).toBeDisabled();
    // The JSON export does not depend on the selector, so it stays available.
    await expect(page.getByRole("button", { name: /Export workspace/ })).toBeEnabled();

    // retry: false stands — a mount makes one attempt, not a storm.
    await page.waitForTimeout(2000);
    expect(resources.attempts.length).toBe(1);

    resources.resourcesFail = false;
    resources.delayMs = 1500;
    await retry.click();

    // One press, one request, even while the request is still in flight.
    await page.waitForTimeout(500);
    expect(resources.attempts.length).toBe(2);
    // The card and its alert survive the in-flight retry, and Retry is shown
    // disabled instead of unmounted, so it cannot be pressed a second time.
    await expect(page.getByText("Data export")).toBeVisible();
    await expect(alert).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeDisabled();

    await expect(alert).toBeHidden();
    await expect(page.getByRole("button", { name: "Export CSV" })).toBeEnabled();
    await expect(page.getByRole("combobox")).toContainText("members");
    // One press, one request: the recovery path never refetches on its own.
    expect(resources.attempts.length).toBe(2);
    expect(errors).toEqual([]);
  });

  test("a failed retry keeps the card usable", async ({ page, resources }) => {
    const errors = await pageerrors(page);
    resources.resourcesFail = true;
    await openSettings(page, resources);

    await expect(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: "Retry" }).click();

    // The card comes back in the failed state, not stuck on a spinner.
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeEnabled();
    expect(resources.attempts.length).toBe(2);
    expect(errors).toEqual([]);
  });
});
