import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * The webhooks pages use the refine resource `webhooks`, which the dataProvider
 * maps to the `webhooks/subscriptions` collection the API serves — the router
 * has no collection at its own prefix. These specs pin that mapping for the
 * list, create and delete calls, and the one distinction the list view used to
 * lose: a request that failed is not a list that came back empty.
 */

const SUBSCRIPTION = {
  id: "sub-1",
  workspace_id: "ws-1",
  url: "https://example.com/hooks/acme",
  events: ["invoice.paid"],
  active: true,
  created_at: "2026-01-01T00:00:00Z",
};

const COLLECTION = "/api/v1/webhooks/subscriptions";

/**
 * The access token lives in memory only, so a cold load boots without one and
 * `RequireWorkspace` sends a deep link to `/` before the session restore lands
 * (the mock's `/auth/me` is too fast). Seeding the persisted identity gives the
 * provider its workspace on the first render, so the page under test is the one
 * that renders.
 */
const webhooks = async (page: Page) => {
  await mockApi(page, { signedIn: true });
  await page.addInitScript((identity) => {
    window.localStorage.setItem("tf_identity", JSON.stringify(identity));
  }, IDENTITY);
};

/** Answer the subscriptions collection with a fixed status + body. */
const subscriptions = (page: Page, status: number, body: unknown) =>
  page.route(
    (url) => url.pathname.startsWith(COLLECTION),
    (route) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }),
  );

/** Record every webhook API call and let the stub below answer it. Registered last, so it sees every webhook request first and falls through to the stub. */
const recordWebhookCalls = (page: Page, calls: string[]) =>
  page.route(
    (url) => url.pathname.startsWith("/api/v1/webhooks"),
    (route) => {
      calls.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
      return route.fallback();
    },
  );

const events = (page: Page) =>
  page.route(
    (url) => url.pathname === "/api/v1/webhooks/events",
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ events: ["invoice.paid"] }),
      }),
  );

test.describe("webhooks page", () => {
  test("reads the subscriptions collection, not the router prefix", async ({ page }) => {
    await webhooks(page);
    await subscriptions(page, 200, [SUBSCRIPTION]);
    const calls: string[] = [];
    await recordWebhookCalls(page, calls);

    await page.goto("/webhooks");

    // The row is the evidence the response reached the table; the recorded call
    // is the evidence of which endpoint produced it.
    await expect(page.getByText(SUBSCRIPTION.url)).toBeVisible();
    expect(calls).toContain(`GET ${COLLECTION}`);
  });

  test("a failed request reads as an error, not as an empty list", async ({ page }) => {
    await webhooks(page);
    await subscriptions(page, 500, { detail: "Boom" });

    await page.goto("/webhooks");

    const row = page.getByRole("row").filter({ hasText: "Could not load" });
    await expect(row).toBeVisible();
    await expect(row).toContainText("Boom");
    await expect(page.getByText("No webhook subscriptions yet.")).toHaveCount(0);
  });

  test("an empty collection renders the empty state", async ({ page }) => {
    await webhooks(page);
    await subscriptions(page, 200, []);

    await page.goto("/webhooks");

    await expect(page.getByText("No webhook subscriptions yet.")).toBeVisible();
  });

  test("create and delete target the same collection", async ({ page }) => {
    await webhooks(page);
    await subscriptions(page, 200, [SUBSCRIPTION]);
    await events(page);
    await page.route(
      // mockApi matches on the path only; the created record is this one POST.
      (url) => url.pathname === COLLECTION && url.search === "",
      (route) =>
        route.request().method() === "POST"
          ? route.fulfill({
              status: 201,
              contentType: "application/json",
              body: JSON.stringify({ ...SUBSCRIPTION, secret: "whsec_test" }),
            })
          : route.fallback(),
    );
    const calls: string[] = [];
    await recordWebhookCalls(page, calls);

    await page.goto("/webhooks/create");
    await page.getByLabel("Target URL").fill(SUBSCRIPTION.url);
    await page.getByLabel("invoice.paid").check();
    await page.getByRole("button", { name: "Create webhook" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(calls).toContain(`POST ${COLLECTION}`);

    await page.getByRole("button", { name: "Done" }).click();
    const row = page.getByRole("row").filter({ hasText: SUBSCRIPTION.url });
    await row.getByRole("button", { name: "Delete" }).click();
    // The row also holds the trigger, so the popover's confirm is the last one.
    await page.getByRole("button", { name: "Delete" }).last().click();
    await expect
      .poll(() => calls.filter((call) => call.startsWith("DELETE")))
      .toEqual([`DELETE ${COLLECTION}/sub-1`]);
  });
});