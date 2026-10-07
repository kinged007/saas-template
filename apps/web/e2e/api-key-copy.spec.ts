import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * The created-key dialog in ApiKeyCreatePage has a cancel path, so the copy
 * confirmation has to be reset with it: the dialog goes away with the key it
 * copies, and a stale "Copied" would greet the next created key.
 *
 * The button keeps its accessible name across the copy (#1075); the
 * announcement goes to the dialog's `role="status"` region instead.
 */

const CREATED = { id: "key-1", key: "sk_live_e2e", permissions: ["invoices:read"] };

/** The live region inside the created-key dialog: one per dialog. */
const status = (page: Page) => page.getByRole("dialog").getByRole("status");

const apiKeys = async (page: Page) => {
  await page.context().grantPermissions(["clipboard-write"]);
  await mockApi(page, { signedIn: true });
  await page.addInitScript((identity) => {
    window.localStorage.setItem("tf_identity", JSON.stringify(identity));
  }, IDENTITY);
  // Registered after mockApi so it answers the create before the generic stub.
  await page.route(
    (url) => url.pathname === "/api/v1/api-keys" && url.search === "",
    (route) =>
      route.request().method() === "POST"
        ? route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify(CREATED),
          })
        : route.fallback(),
  );
  await page.goto("/api-keys/create");
  await page.getByLabel("Name", { exact: true }).fill("ci-deploy");
};

test("dismissing the created-key dialog drops the copy confirmation", async ({ page }) => {
  await apiKeys(page);
  await page.getByRole("button", { name: "Create API key" }).click();

  const copy = page.getByRole("button", { name: "Copy API key", exact: true });
  await expect(copy).toHaveAccessibleName("Copy API key");
  await expect(copy).toHaveAttribute("title", "Copy API key");

  await copy.click();
  // The name stays (the button stays focused — a rename would be announced only
  // opportunistically); the live region carries the confirmation.
  await expect(copy).toHaveAccessibleName("Copy API key");
  await expect(copy).toHaveAttribute("title", "Copy API key");
  await expect(copy).toBeFocused();
  await expect(copy.locator("svg.lucide-check")).toBeVisible();
  await expect(status(page)).toHaveText("API key copied");

  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Create API key" }).click();

  await expect(copy).toHaveAccessibleName("Copy API key");
  // The dialog's region remounts with the key: any stale confirmation here
  // would greet the next created key, so the text must be empty again.
  await expect(status(page)).toHaveText("");
});
