import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * RequireWorkspace (src/App.tsx) sends a workspace-scoped route to the
 * dashboard while the identity holds no workspace. Every API call is mocked,
 * so these run against the dev server with no backend or database.
 */

/** Asserts on the pathname, so a redirect may add a query string. */
const path = (page: Page) => expect.poll(() => new URL(page.url()).pathname);

/** Zero workspaces is a settled identity, so the guard's redirect is correct here. */
const NO_WORKSPACES = { ...IDENTITY, workspaces: [], single_workspace: false };

const ANNOUNCEMENT = "You need a workspace to open that page. Showing your dashboard instead.";

/** sonner's <Toaster>: the only aria-live region on the page, one <li> per toast. */
const liveRegion = (page: Page) => page.locator('section[aria-live="polite"]');

const member = (email: string) => ({
  id: "user-2",
  email,
  first_name: "Member",
  last_name: "User",
  membership_id: "mem-2",
  role_id: "1",
  role: "admin",
  status: "active",
  joined_at: "2026-01-01T00:00:00Z",
});

const members = (page: Page, rows: unknown[]) =>
  page.route(
    (url) => url.pathname.endsWith("/api/v1/members"),
    (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rows) }),
  );

test.describe("workspace guard", () => {
  test("a slow identity does not redirect a workspace-scoped route", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await members(page, [member("member@example.com")]);
    // Registered after mockApi, which wins by reverse registration order:
    // /auth/me answers 1.5s late, so the guard has to wait for the identity
    // instead of reading an empty workspace list off an unresolved one.
    await page.route(
      (url) => url.pathname.endsWith("/api/v1/auth/me"),
      async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(IDENTITY),
        });
      },
    );
    await page.goto("/members");
    await path(page).toBe("/members");
    // The row, not the URL alone: a URL-only check also passes on the dashboard.
    await expect(page.getByRole("row").filter({ hasText: "member@example.com" })).toBeVisible();
  });

  for (const legacy of ["/roles", "/jobs"]) {
    test(`the legacy ${legacy} URL redirects once for a user in zero workspaces`, async ({ page }) => {
      await mockApi(page, { signedIn: true, identity: NO_WORKSPACES });
      const visited: string[] = [];
      page.on("framenavigated", (frame) => {
        if (frame === page.mainFrame()) visited.push(new URL(frame.url()).pathname);
      });
      await page.goto(legacy);
      await path(page).toBe("/");
      // Both orders end at "/", so only the trace tells them apart: declared
      // outside the guard, the legacy stub commits the workspace-scoped URL
      // first and the guard then rejects it, for two navigations instead of one.
      // Non-empty first, so an empty trace fails instead of passing both sides.
      expect(visited.length).toBeGreaterThan(0);
      expect(visited).not.toContain(`/settings/workspace/${legacy.slice(1)}`);
    });
  }

  test("a user with a workspace is neither redirected nor announced", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await members(page, [member("member@example.com")]);
    await page.goto("/members");
    await path(page).toBe("/members");
    // The row, not the URL alone: it also proves the page has rendered, so the
    // sampling below starts with the guard already mounted.
    await expect(page.getByRole("row").filter({ hasText: "member@example.com" })).toBeVisible();
    // Sampled, not awaited: sonner auto-dismisses after 4s, so a polled
    // toHaveCount(0) would wait the toast out and pass even if it fired. A count
    // read at one instant cannot pass that way.
    const cards = liveRegion(page).locator("li");
    for (let i = 0; i < 10; i++) {
      expect(await cards.count()).toBe(0);
      await page.waitForTimeout(200);
    }
  });

  test("the redirect is announced once inside a live region", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: NO_WORKSPACES });
    await page.goto("/api-keys");
    await path(page).toBe("/");
    // sonner's <Toaster> is the only aria-live region on the page: text that is
    // merely rendered on the page is not announced to a screen reader. The whole
    // sentence, so another workspace-flavoured toast cannot stand in for it.
    const region = liveRegion(page);
    // The count and the text in one poll, read in the same instant: sonner
    // auto-dismisses after 4s, so two separate assertions can straddle it on a
    // slow runner. One card, not two: StrictMode double-invokes the guard's
    // mount effect, and sonner dedups on a supplied id, so a bare toast() would
    // show two.
    await expect
      .poll(async () => ({
        cards: await region.locator("li").count(),
        text: (await region.textContent()) ?? "",
      }))
      .toEqual({ cards: 1, text: expect.stringContaining(ANNOUNCEMENT) });
  });
});
