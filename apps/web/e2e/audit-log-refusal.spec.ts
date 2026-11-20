import { expect } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

// The refusal behavior — a failure row, no duplicate toast — must hold on both
// consumers of the shared AuditLogTable. The admin route is a virtual
// resource: its list reads GET /api/v1/admin/audit. The route globs do not
// overlap: `**/api/v1/audit**` does not match `/api/v1/admin/audit`.
const AUDIT_ROUTES = [
  { path: "/settings/workspace/audit", url: "**/api/v1/audit**" },
  { path: "/admin/audit", url: "**/api/v1/admin/audit**" },
] as const;

/**
 * A refused query has to read as a failure, not as an empty log. `node --test`
 * loads no DOM, so this suite is the only mechanism that can guard it.
 */
test.describe("audit log fetch", () => {
  for (const audit of AUDIT_ROUTES) {
    test(`a 403 renders the failure instead of an empty log (${audit.path})`, async ({ page }) => {
      await mockApi(page, { signedIn: true });
      let calls = 0;
      await page.route(audit.url, (route) => {
        calls += 1;
        return route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({ detail: "You do not have permission to perform this action." }),
        });
      });

      await page.goto(audit.path);

      const failure = page.getByRole("row").filter({ hasText: "Could not load audit entries." });
      await expect(failure).toBeVisible();
      // The row swaps from "Loading…" to the failure text without a page load,
      // so the cell is a `status` live region: without it the transition is
      // never announced.
      await expect(
        page.getByRole("status").filter({ hasText: "Could not load audit entries." }),
      ).toBeVisible();
      // Unscoped: refine's error toast used to repeat the reason, which forced
      // a row-scoped locator here. The row keeps the server's detail — it is
      // the only thing that tells the user why the query failed.
      await expect(
        page.getByText(/Could not load audit entries\. You do not have permission/),
      ).toHaveCount(1);
      // And the toast must not repeat it. The wait covers the effect that
      // raises the notification after the row paints, and the count is read
      // once: the toast clears about a second later, and a retrying assertion
      // would pass on the dismissed toast. The locator is scoped to the
      // failure reason — an unrelated toast on the page is some other
      // component's failure, not this row's duplicate. Verified to still fail
      // against the pre-#1234 build.
      await page.waitForTimeout(500);
      expect(
        await page.locator('[data-sonner-toast]:has-text("You do not have permission")').count(),
      ).toBe(0);
      await expect(page.getByText("No audit entries yet.")).toHaveCount(0);
      // The failure row's only recovery affordance is present whatever the
      // status that landed there.
      await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
      // The footer counts rows it never received, so a refused query drops it
      // rather than asserting "0 entries" under the failure row.
      await expect(page.getByText(/^Showing 0/)).toHaveCount(0);
      await expect(page.getByText("Page 1 of 1")).toHaveCount(0);
      // The shared client does not retry a 4xx, so this is the StrictMode
      // baseline and not the tail of a retry budget.
      await page.waitForTimeout(1_500);
      expect(calls).toBe(2);
    });
  }

  // Both the 403 refusal and a 5xx land in the same failure row, so its
  // only recovery affordance has to work for either status.
  test("Try again re-runs the query and recovers when the failure clears", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    let calls = 0;
    let succeed = false;
    await page.route("**/api/v1/audit**", (route) => {
      calls += 1;
      return route.fulfill({
        status: succeed ? 200 : 500,
        contentType: "application/json",
        body: succeed ? "[]" : "{}",
      });
    });

    await page.goto("/settings/workspace/audit");
    await expect(
      page.getByRole("row").filter({ hasText: "Could not load audit entries." }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();

    const before = calls;
    succeed = true;
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByText("No audit entries yet.")).toBeVisible();
    // The click drove new request(s): the row recovery is the query
    // refetching, not stale `list` data from anywhere else.
    expect(calls).toBeGreaterThan(before);
    await expect(page.getByText(/Could not load audit entries\./)).toHaveCount(0);
  });

  test("a 5xx fails on the first attempt", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    let calls = 0;
    await page.route("**/api/v1/audit**", (route) => {
      calls += 1;
      return route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
    });

    await page.goto("/settings/workspace/audit");

    await expect(
      page.getByRole("row").filter({ hasText: "Could not load audit entries." }),
    ).toBeVisible();
    await expect(page.getByText("No audit entries yet.")).toHaveCount(0);
    await expect(page.getByText(/^Showing 0/)).toHaveCount(0);
    await expect(page.getByText("Page 1 of 1")).toHaveCount(0);
    // The shared client does not retry a 5xx either, so this is the
    // StrictMode baseline and not the tail of a retry budget.
    await page.waitForTimeout(1_500);
    expect(calls).toBe(2);
  });

  test("a request with no response fails on the first attempt", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    let calls = 0;
    await page.route("**/api/v1/audit**", (route) => {
      calls += 1;
      return route.abort("failed");
    });

    await page.goto("/settings/workspace/audit");

    await expect(
      page.getByRole("row").filter({ hasText: "Could not load audit entries." }),
    ).toBeVisible();
    await expect(page.getByText("No audit entries yet.")).toHaveCount(0);
    await expect(page.getByText(/^Showing 0/)).toHaveCount(0);
    await expect(page.getByText("Page 1 of 1")).toHaveCount(0);
    // The shared client does not retry a request that produced no response,
    // so this is the StrictMode baseline and not the tail of a retry budget.
    await page.waitForTimeout(1_500);
    expect(calls).toBe(2);
  });

  test("a genuinely empty log still says it is empty", async ({ page }) => {
    await mockApi(page, { signedIn: true });

    await page.goto("/settings/workspace/audit");

    await expect(page.getByText("No audit entries yet.")).toBeVisible();
    await expect(page.getByText(/Could not load audit entries\./)).toHaveCount(0);
    await expect(page.getByText("Page 1 of 1")).toBeVisible();
  });
});
