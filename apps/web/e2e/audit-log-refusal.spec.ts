import { expect } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

const AUDIT = "**/api/v1/audit**";

/**
 * A refused query has to read as a failure, not as an empty log. `node --test`
 * loads no DOM, so this suite is the only mechanism that can guard it.
 */
test.describe("audit log fetch", () => {
  test("a 403 renders the failure instead of an empty log", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    let calls = 0;
    await page.route(AUDIT, (route) => {
      calls += 1;
      return route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "You do not have permission to perform this action." }),
      });
    });

    await page.goto("/settings/workspace/audit");

    const failure = page.getByRole("row").filter({ hasText: "Could not load audit entries." });
    await expect(failure).toBeVisible();
    // Scoped to the row: refine's error notification repeats the same message
    // in a toast, so an unscoped getByText resolves to two elements.
    await expect(failure).toContainText("You do not have permission to perform this action.");
    await expect(page.getByText("No audit entries yet.")).toHaveCount(0);
    // The footer counts rows it never received, so a refused query drops it
    // rather than asserting "0 entries" under the failure row.
    await expect(page.getByText(/^Showing 0/)).toHaveCount(0);
    await expect(page.getByText("Page 1 of 1")).toHaveCount(0);
    // The shared client does not retry a 4xx, so this is the StrictMode
    // baseline and not the tail of a retry budget.
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