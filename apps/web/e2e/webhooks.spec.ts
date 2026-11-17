import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * The webhooks pages use the refine resource `webhooks`, which the dataProvider
 * maps to the `webhooks/subscriptions` collection the API serves — the router
 * has no collection at its own prefix. These specs pin that mapping for the
 * list, create and delete calls, and the one distinction the list and the
 * delivery log used to lose: a request that failed is not a list that came
 * back empty.
 */

const SUBSCRIPTION = {
  id: "sub-1",
  workspace_id: "ws-1",
  url: "https://example.com/hooks/acme",
  // A real event name: the API rejects unknown ones with 422, so a fixture
  // inventing one would let the stubbed list and a real create diverge.
  events: ["apikey.created"],
  active: true,
  created_at: "2026-01-01T00:00:00Z",
};

const DELIVERIES = "/api/v1/webhooks/deliveries";

const DELIVERY = {
  id: "del-1",
  subscription_id: "sub-1",
  workspace_id: "ws-1",
  event_type: "apikey.created",
  subject: "apikey/ak-1",
  // The API only writes pending/success/exhausted — nothing ever assigns
  // `WebhookDeliveryStatus.FAILED` — so the fixture states the terminal value
  // a real row with `error` set would carry.
  status: "exhausted",
  attempt_count: 3,
  response_status: 500,
  error: "Upstream returned 500",
  created_at: "2026-01-02T00:00:00Z",
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
        body: JSON.stringify({ events: ["apikey.created"] }),
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

  test("a failed subscriptions load reports the failure once, in the row", async ({
    page,
  }) => {
    await webhooks(page);
    await subscriptions(page, 500, { detail: "Permission denied" });

    await page.goto("/webhooks");

    const row = page.getByRole("row").filter({ hasText: "Could not load" });
    await expect(row).toContainText("Permission denied");
    await page.waitForTimeout(500);
    expect(
      await page.locator('[data-sonner-toast]:has-text("Permission denied")').count(),
    ).toBe(0);
  });

  test("an empty collection renders the empty state", async ({ page }) => {
    await webhooks(page);
    await subscriptions(page, 200, []);

    await page.goto("/webhooks");

    await expect(page.getByText("No webhook subscriptions yet.")).toBeVisible();
  });

  test("a failed delivery request reads as an error, not as an empty log", async ({ page }) => {
    await webhooks(page);
    await subscriptions(page, 200, [SUBSCRIPTION]);
    await page.route(
      (url) => url.pathname.startsWith("/api/v1/webhooks/deliveries"),
      (route) =>
        route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Boom" }),
        }),
    );

    await page.goto("/webhooks");
    await page.getByRole("button", { name: "Delivery log" }).click();

    const row = page.getByRole("row").filter({ hasText: "Could not load deliveries" });
    await expect(row).toBeVisible();
    await expect(row).toContainText("Boom");
    await expect(page.getByText("No deliveries yet.")).toHaveCount(0);
  });

  // The shared client refuses a 5xx on the first attempt, so the dead-end
  // failure rows are the only recovery: with refetchOnWindowFocus off, a
  // refused load otherwise waits for a remount or a reload.
  test("Try again re-runs the refused subscriptions query and recovers", async ({ page }) => {
    await webhooks(page);
    let calls = 0;
    let succeed = false;
    await page.route(
      (url) => url.pathname.startsWith(COLLECTION),
      (route) => {
        calls += 1;
        return route.fulfill({
          status: succeed ? 200 : 500,
          contentType: "application/json",
          body: succeed ? "[]" : JSON.stringify({ detail: "Boom" }),
        });
      },
    );

    await page.goto("/webhooks");
    const row = page.getByRole("row").filter({ hasText: "Could not load" });
    await expect(row).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();

    const before = calls;
    succeed = true;
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByText("No webhook subscriptions yet.")).toBeVisible();
    // The click drove new request(s): the recovery is the query refetching,
    // not stale `list` data from anywhere else.
    expect(calls).toBeGreaterThan(before);
    await expect(row).toHaveCount(0);
  });

  test("Try again re-runs the refused delivery log and recovers", async ({ page }) => {
    await webhooks(page);
    await subscriptions(page, 200, [SUBSCRIPTION]);
    let calls = 0;
    let succeed = false;
    await page.route(
      (url) => url.pathname.startsWith(DELIVERIES),
      (route) => {
        calls += 1;
        return route.fulfill({
          status: succeed ? 200 : 500,
          contentType: "application/json",
          body: succeed ? "[]" : JSON.stringify({ detail: "Boom" }),
        });
      },
    );

    await page.goto("/webhooks");
    await page.getByRole("button", { name: "Delivery log" }).click();
    const row = page.getByRole("row").filter({ hasText: "Could not load deliveries" });
    await expect(row).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();

    const before = calls;
    succeed = true;
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByText("No deliveries yet.")).toBeVisible();
    expect(calls).toBeGreaterThan(before);
    await expect(row).toHaveCount(0);
  });

  test("a deliveries payload that is not an array renders the empty state", async ({ page }) => {
    await webhooks(page);
    await subscriptions(page, 200, [SUBSCRIPTION]);
    // refine hands back a frozen empty object as `result.data` when the query
    // has no data (a disabled query reports neither loading nor error), so a
    // non-array has to survive the render instead of reaching `rows.map`.
    await page.route(
      (url) => url.pathname.startsWith(DELIVERIES),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ deliveries: [] }),
        }),
    );

    await page.goto("/webhooks");
    await page.getByRole("button", { name: "Delivery log" }).click();

    await expect(page.getByText("No deliveries yet.")).toBeVisible();
  });

  test("a redeliver refetches the log, and a failed refetch keeps the rows", async ({ page }) => {
    await webhooks(page);
    await subscriptions(page, 200, [SUBSCRIPTION]);
    let queued = false;
    let readsAfterQueue = 0;
    await page.route(
      (url) => url.pathname.startsWith(DELIVERIES),
      (route) => {
        if (route.request().method() === "POST") {
          queued = true;
          // The redeliver route declares no status_code, so it answers 200 with
          // the delivery record — `dispatch_due` has already reset its status.
          return route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ ...DELIVERY, status: "pending" }),
          });
        }
        // The refetch fails while the rows it had are still good. A 403 is used
        // over a 500 because a client error skips react-query's retry budget
        // and lands in `isError` at once.
        if (queued) readsAfterQueue += 1;
        return route.fulfill({
          status: queued ? 403 : 200,
          contentType: "application/json",
          body: queued
            ? JSON.stringify({ detail: "Not allowed to read deliveries" })
            : JSON.stringify([DELIVERY]),
        });
      },
    );

    await page.goto("/webhooks");
    await page.getByRole("button", { name: "Delivery log" }).click();
    // The delivery row carries its error text, which the subscription row has
    // no cell for. `.last()` because the log renders inside the subscription
    // row, so the filter also matches that outer row.
    const row = page.getByRole("row").filter({ hasText: DELIVERY.error }).last();
    await expect(row).toBeVisible();
    // Rows without the staleness caption can only mean the log is current.
    await expect(page.getByText("Showing the last deliveries loaded.")).toHaveCount(0);

    await page.getByRole("button", { name: "Redeliver" }).click();

    // The redeliver targets the deliveries query itself, so the log refetches…
    await expect.poll(() => readsAfterQueue).toBeGreaterThan(0);
    // …and the failed refetch leaves the rows it already had on screen.
    await expect(row).toBeVisible();
    // The failure is captioned next to the table, so stale rows are
    // distinguishable from a current list.
    await expect(page.getByText("Showing the last deliveries loaded.")).toBeVisible();
    await expect(page.getByText("Could not load deliveries")).toHaveCount(0);
  });

  test("a failed log refetch captions an empty cached list", async ({ page }) => {
    await webhooks(page);
    await subscriptions(page, 200, [SUBSCRIPTION]);
    let refused = false;
    await page.route(
      (url) => url.pathname.startsWith(DELIVERIES),
      (route) =>
        route.fulfill(
          refused
            ? {
                status: 403,
                contentType: "application/json",
                body: JSON.stringify({ detail: "Not allowed to read deliveries" }),
              }
            : { status: 200, contentType: "application/json", body: JSON.stringify([]) },
        ),
    );

    // The log loads an empty list, then the pane is closed and reopened: the
    // mount refetch fails while the cached empty list is what renders. That
    // is the empty-list twin of the redeliver spec above — the empty state
    // must not read as current.
    await page.goto("/webhooks");
    await page.getByRole("button", { name: "Delivery log" }).click();
    await expect(page.getByText("No deliveries yet.")).toBeVisible();

    refused = true;
    await page.getByRole("button", { name: "Hide log" }).click();
    await page.getByRole("button", { name: "Delivery log" }).click();

    await expect(page.getByText("Showing the last deliveries loaded.")).toBeVisible();
    await expect(page.getByText("No deliveries yet.")).toBeVisible();
    await expect(page.getByText("Could not load deliveries")).toHaveCount(0);
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
    await page.getByLabel("apikey.created").check();
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

  test("a bulk delete targets the collection, not the router prefix", async ({ page }) => {
    await webhooks(page);
    await subscriptions(page, 200, [SUBSCRIPTION]);
    await page.route(
      (url) => url.pathname.startsWith(`${COLLECTION}/sub-`),
      (route) => route.fulfill({ status: 204, contentType: "application/json", body: "" }),
    );
    const calls: string[] = [];
    await recordWebhookCalls(page, calls);

    await page.goto("/webhooks");
    // No page has a bulk-delete affordance, so the verb is driven through the
    // provider the app itself uses. The specifier is assembled at run time
    // because tsc would try to resolve the dev-server URL statically; vite
    // serves this exact path, so it is the module instance already in memory —
    // which matters, the access token lives in that module's memory only.
    const deleted = await page.evaluate(async () => {
      const specifier = ["/src/providers", "dataProvider.ts"].join("/");
      const { dataProvider } = (await import(/* @vite-ignore */ specifier)) as {
        dataProvider: {
          deleteMany: (params: { resource: string; ids: string[] }) => Promise<{ data: unknown[] }>;
        };
      };
      const { data } = await dataProvider.deleteMany({
        resource: "webhooks",
        ids: ["sub-1", "sub-2"],
      });
      return data;
    });

    expect(deleted).toHaveLength(2);
    // The fan-out is concurrent, so the order is not fixed.
    expect([...calls].filter((call) => call.startsWith("DELETE")).sort()).toEqual(
      [`DELETE ${COLLECTION}/sub-1`, `DELETE ${COLLECTION}/sub-2`].sort(),
    );
  });
});
