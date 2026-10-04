import { expect, type Locator, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * The webhook-secret and API-key copy buttons are icon-only, so each carries the
 * `title` + `aria-label` pair #332 established: `title` paints the hover
 * tooltip, `aria-label` is what a screen reader announces. A control with
 * neither is announced as a bare "button".
 *
 * Both pages share one `CopyButton`, so the pair is asserted equal on each:
 * the accessible name is the invariant and `title` duplicates it, and a control
 * whose two disagree announces one action and hovers another (WCAG 2.5.3,
 * Label in Name). The icon flips to a check for 1.5 s after the write, so the
 * name flips with it — a button that still reads "Copy …" in the copied state
 * announces the action just performed instead of a confirmation. The same shape
 * `security-2fa-copy.spec.ts` pins for the 2FA control.
 */

const API_KEY = {
  id: "key-1",
  workspace_id: "ws-1",
  name: "ci-deploy",
  key: "tf_live_test",
  permissions: [],
  usage_quota: null,
  expires_at: null,
  created_at: "2026-01-01T00:00:00Z",
  last_used_at: null,
  revoked_at: null,
};

const SUBSCRIPTION = {
  id: "sub-1",
  workspace_id: "ws-1",
  url: "https://example.com/hooks/acme",
  events: ["invoice.paid"],
  active: true,
  created_at: "2026-01-01T00:00:00Z",
  secret: "whsec_test",
};

/**
 * The access token lives in memory only, so a cold load boots without one and
 * the guard sends a deep link to `/` before the session restore lands. Seeding
 * the persisted identity renders the page under test on the first pass.
 */
const signedIn = async (page: Page) => {
  await mockApi(page, { signedIn: true });
  await page.addInitScript((identity) => {
    window.localStorage.setItem("tf_identity", JSON.stringify(identity));
  }, IDENTITY);
};

/** Answer the create POST on `path` with `record`; every other call falls through. Registered last, so it sees the request first. */
const created = (page: Page, path: string, record: unknown) =>
  page.route(
    (url) => url.pathname === path,
    (route) =>
      route.request().method() === "POST"
        ? route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify(record),
          })
        : route.fallback(),
  );

/**
 * The button is named, `title` matches the name, and the name flips to the
 * confirmation after the write. Asserting the name twice is the point: a stale
 * label fails the second query instead of passing on the swapped icon.
 */
async function expectCopyButtonAnnounces(copy: Locator, label: string) {
  await expect(copy).toBeVisible();
  expect(await copy.getAttribute("aria-label"), "icon-only button with no accessible name").toBe(label);
  expect(await copy.getAttribute("title"), "title and aria-label disagree").toBe(label);

  await copy.click();

  const confirmed = copy.page().getByRole("button", { name: "Copied", exact: true });
  await expect(confirmed).toBeVisible();
  await expect(copy).toHaveCount(0);
  expect(await confirmed.getAttribute("title"), "title and aria-label disagree").toBe("Copied");
}

test.beforeEach(async ({ page }) => {
  // The write has to resolve for the icon to flip; a denied one would fail the
  // assertions below for the wrong reason.
  await page.context().grantPermissions(["clipboard-write"]);
});

test("the API-key copy button announces the copy, then the confirmation", async ({ page }) => {
  await signedIn(page);
  await created(page, "/api/v1/api-keys", API_KEY);

  await page.goto("/api-keys/create");
  await page.getByLabel("Name").fill(API_KEY.name);
  await page.getByRole("button", { name: "Create API key" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();

  await expectCopyButtonAnnounces(
    page.getByRole("button", { name: "Copy API key", exact: true }),
    "Copy API key",
  );
});

test("the webhook-secret copy button announces the copy, then the confirmation", async ({ page }) => {
  await signedIn(page);
  await page.route(
    (url) => url.pathname === "/api/v1/webhooks/events",
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ events: ["invoice.paid"] }),
      }),
  );
  await created(page, "/api/v1/webhooks/subscriptions", SUBSCRIPTION);

  await page.goto("/webhooks/create");
  await page.getByLabel("Target URL").fill(SUBSCRIPTION.url);
  await page.getByLabel("invoice.paid").check();
  await page.getByRole("button", { name: "Create webhook" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();

  await expectCopyButtonAnnounces(
    page.getByRole("button", { name: "Copy signing secret", exact: true }),
    "Copy signing secret",
  );
});