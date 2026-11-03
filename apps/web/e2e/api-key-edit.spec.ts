import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The ApiKeysPage Edit dialog patches name, quota and expiry in one call —
 * explicitly sent fields change, so clearing quota or expiry reads as a
 * clear. Every API call is mocked, so no backend (and no DATABASE_URL) is
 * needed.
 */

const KEY = {
  id: "key-1",
  workspace_id: "ws-1",
  name: "ci-deploy",
  key_prefix: "sk_live_AbCdEfGh",
  permissions: ["member:read"],
  usage_quota: 100,
  usage_count: 4,
  usage_window_count: 2,
  usage_window_start: "2026-01-01T00:00:00Z",
  last_used_at: null,
  expires_at: "2027-01-01T00:00:00Z",
  revoked_at: null,
  created_at: "2026-01-01T00:00:00Z",
};

const apiKeys = (page: Page) =>
  page.route(
    (url) => url.pathname === "/api/v1/api-keys",
    (route) =>
      route.request().method() === "GET"
        ? route.fulfill({
            status: 200,
            contentType: "application/json",
            headers: { "x-total-count": "1" },
            body: JSON.stringify([current]),
          })
        : route.fallback(),
  );

let current: Record<string, unknown>;

test.describe("api key edit", () => {
  test("saving sends the edited fields and refreshes the row", async ({ page }) => {
    current = { ...KEY };
    await mockApi(page, { signedIn: true });
    await apiKeys(page);
    let patched: unknown = null;
    await page.route(
      (url) => url.pathname === "/api/v1/api-keys/key-1",
      (route) =>
        route.request().method() === "PATCH"
          ? (async () => {
              patched = route.request().postDataJSON();
              current = { ...KEY, name: "ci-nightly", usage_quota: null, expires_at: null };
              await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify(current),
              });
            })()
          : route.fallback(),
    );
    await page.goto("/api-keys");

    await expect(page.getByText("ci-deploy", { exact: true })).toBeVisible();
    await page.getByTitle("Edit key").click();

    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Name").fill("ci-nightly");
    await dialog.getByLabel("Monthly usage quota").fill("");
    await dialog.getByLabel("Never expires").check();
    await dialog.getByRole("button", { name: "Save changes" }).click();

    await expect
      .poll(() => patched, { timeout: 10_000 })
      .toEqual({ name: "ci-nightly", usage_quota: null, expires_at: null });
    await expect(page.getByText("API key updated")).toBeVisible();
    await expect(page.getByText("ci-nightly", { exact: true })).toBeVisible();
  });
});
