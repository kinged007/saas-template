import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * Regression tests for the workspace export card. Every API call is mocked, so
 * these run against the dev server with no backend or database.
 */
// The trailing `**` is needed: the card sends this request with an empty query
// string, and a glob that stops at the path does not match it.
const RESOURCES_PATH = "**/api/v1/workspaces/export/resources**";

/**
 * How GET /workspaces/export/resources answers. `fail` picks the answer,
 * `delayMs` is spent before answering — failure included, so a retry that
 * takes its time can be caught mid-flight — and every request is counted, which
 * is how the one-attempt-per-press and no-auto-retry claims are checked.
 */
type ResourcesMock = { fail: boolean; delayMs?: number; attempts: number[] };

async function mockResources(page: Page, state: ResourcesMock) {
  await page.route(RESOURCES_PATH, async (route) => {
    state.attempts.push(Date.now());
    if (state.delayMs) await new Promise((resolve) => setTimeout(resolve, state.delayMs));
    if (state.fail) return route.abort("failed");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ resources: ["members", "roles", "audit"] }),
    });
  });
}

/**
 * /settings/workspace/general renders three comboboxes — the sidebar workspace
 * switcher, this card's resource select, the danger-zone owner picker — so the
 * select is reached through the card it sits in, not by page position.
 */
const exportCard = (page: Page) => page.locator("div.rounded-xl").filter({ hasText: "Data export" });

const openSettings = async (page: Page, state: ResourcesMock) => {
  await mockApi(page, { signedIn: true });
  await mockResources(page, state);
  await page.goto("/settings/workspace/general");
  await expect(exportCard(page)).toBeVisible();
};

test.describe("workspace export card", () => {
  test("the description promises no import and names what the JSON contains", async ({ page }) => {
    await openSettings(page, { fail: false, attempts: [] });

    const description = page.getByText(/Download a read-only snapshot of this workspace/);
    await expect(description).toBeVisible();
    // No import path exists in the API, so the copy must not offer one.
    const text = (await description.textContent()) ?? "";
    expect(text).not.toMatch(/importable|after import/i);
    await expect(description).toContainText("There is no import in this app");
  });

  test("the description states the export caps, the truncated flag and the CSV prefix convention", async ({ page }) => {
    await openSettings(page, { fail: false, attempts: [] });

    const description = page.getByText(/Download a read-only snapshot of this workspace/);
    await expect(description).toBeVisible();
    const text = (await description.textContent()) ?? "";
    // Three sections are capped, so the copy must name the cap and the flag
    // that reports it instead of implying the JSON is always complete.
    expect(text).toContain("5000");
    expect(text).toContain("truncated");
    // The apostrophe prefix is a convention a spreadsheet can drop, not a
    // guarantee, so the copy must not present it as one.
    expect(text).toMatch(/apostrophe/i);
    expect(text).toMatch(/convention|not a guarantee/i);
  });

  test("a failed resources fetch offers a user-pressed retry and recovers", async ({ page }) => {
    const resources: ResourcesMock = { fail: true, attempts: [] };
    await openSettings(page, resources);

    const alert = exportCard(page).getByRole("alert");
    await expect(alert).toContainText("Could not load the exportable resources");
    const retry = exportCard(page).getByRole("button", { name: "Retry" });
    await expect(retry).toBeVisible();
    await expect(exportCard(page).getByRole("button", { name: "Export CSV" })).toBeDisabled();
    // The JSON export does not depend on the selector, so it stays available.
    await expect(page.getByRole("button", { name: /Export workspace/ })).toBeEnabled();

    // retry: false stands — the query is settled once the alert is up (no retry
    // timer, refetchOnWindowFocus off), so a mount makes one attempt, and no
    // wait is needed to show that nothing else arrives.
    await expect.poll(() => resources.attempts.length).toBe(1);

    resources.fail = false;
    resources.delayMs = 1500;
    await retry.click();

    // One press, one request, even while the request is still in flight.
    await expect.poll(() => resources.attempts.length).toBe(2);
    // The card and its alert survive the in-flight retry, and Retry is shown
    // disabled instead of unmounted, so it cannot be pressed a second time.
    await expect(exportCard(page)).toBeVisible();
    await expect(alert).toBeVisible();
    await expect(retry).toBeDisabled();

    await expect(alert).toBeHidden();
    await expect(exportCard(page).getByRole("button", { name: "Export CSV" })).toBeEnabled();
    await expect(exportCard(page).getByRole("combobox")).toContainText("members");
    // One press, one request: the recovery path never refetches on its own.
    expect(resources.attempts.length).toBe(2);
  });

  test("a failed retry keeps the card usable", async ({ page }) => {
    // The retry is answered slowly, so this walks the mid-flight state: the card
    // renders off errorUpdatedAt there, not off the settled error, which is what
    // keeps it mounted and Retry disabled instead of gone.
    const resources: ResourcesMock = { fail: true, delayMs: 1500, attempts: [] };
    await openSettings(page, resources);

    const retry = exportCard(page).getByRole("button", { name: "Retry" });
    await expect(exportCard(page).getByRole("alert")).toBeVisible();
    await expect(retry).toBeEnabled();

    await retry.click();

    // In flight: still the failed card, Retry disabled rather than unmounted.
    await expect.poll(() => resources.attempts.length).toBe(2);
    await expect(exportCard(page)).toBeVisible();
    await expect(retry).toBeDisabled();

    // The card comes back in the failed state, not stuck on a spinner.
    await expect(retry).toBeEnabled();
    expect(resources.attempts.length).toBe(2);
  });
});
