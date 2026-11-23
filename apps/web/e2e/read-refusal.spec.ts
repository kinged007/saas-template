import { expect } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * A refused read is reported once, in the page body, with the server's reason
 * — refine raises no error toast for reads (read-failure.ts). Sonner
 * auto-dismisses after a few seconds, so a retrying zero-count assertion
 * would pass on the dismissed toast: each guard below waits for the
 * notification effect to settle, then reads the toast count exactly once,
 * scoped to the failure reason.
 */

const JOB_ID = "00000000-0000-0000-0000-000000000000";
const toasts = (page: import("playwright/test").Page) =>
  page.locator("[data-sonner-toaster] [data-sonner-toast]");

test("a refused job fetch renders the server's reason and no toast", async ({ page }) => {
  await mockApi(page, {
    signedIn: true,
    failures: {
      [`jobs/${JOB_ID}`]: {
        status: 403,
        detail: "you are not a member of this workspace",
      },
    },
  });
  await page.goto(`/jobs/${JOB_ID}`);

  // The page's own state carries the reason; the old copy claimed the record
  // was missing, which is what made the toast above it read like an exception.
  await expect(
    page.getByText("you are not a member of this workspace"),
  ).toBeVisible();
  await expect(page.getByText("Job not found.")).toHaveCount(0);
  // Settle wait, then a single non-retrying read: a toast that mounted and
  // dismissed must still fail this guard.
  await page.waitForTimeout(500);
  expect(
    await page
      .locator('[data-sonner-toast]:has-text("you are not a member of this workspace")')
      .count(),
  ).toBe(0);
});

test("a refused list fetch renders the reason in the list page", async ({ page }) => {
  await mockApi(page, {
    signedIn: true,
    failures: {
      "api-keys": { status: 500, detail: "internal error" },
    },
  });
  await page.goto("/api-keys");

  await expect(page.getByRole("alert")).toHaveText("internal error");
  await page.waitForTimeout(500);
  expect(
    await page.locator('[data-sonner-toast]:has-text("internal error")').count(),
  ).toBe(0);
});

test("a successful list fetch renders no alert and no toast", async ({ page }) => {
  await mockApi(page, {
    signedIn: true,
    lists: {
      "api-keys": [
        {
          id: "k1",
          name: "CI",
          key_prefix: "tk_",
          permissions: [],
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    },
  });
  await page.goto("/api-keys");

  await expect(page.getByRole("row").filter({ hasText: "CI" })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.waitForTimeout(500);
  expect(await toasts(page).count()).toBe(0);
});
