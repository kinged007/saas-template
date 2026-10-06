import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * The dashboard "Get set up" card tracks work the signed-in identity can
 * actually do. A step it may not perform offers a call to action whose action
 * the backend refuses, and used to keep the card up for good once every
 * permitted step was done, with the manual dismiss as the only way out.
 */

/** Every call the card makes for its own progress, plus any backend 4xx. */
function watchCardRequests(page: Page) {
  const cardCalls: string[] = [];
  const failures: string[] = [];
  page.on("request", (request) => {
    const { pathname } = new URL(request.url());
    if (pathname.endsWith("/invitations") || pathname.endsWith("/api-keys")) {
      cardCalls.push(pathname);
    }
  });
  page.on("response", (response) => {
    // Backend calls only: a dev-server or asset 404 is not this card's doing.
    const { pathname } = new URL(response.url());
    if (pathname.startsWith("/api/v1/") && response.status() >= 400) {
      failures.push(`${response.status()} ${pathname}`);
    }
  });
  return { cardCalls, failures };
}

/** Workspace-scoped permissions live on the workspace entry, not the identity. */
const asRole = (permissions: string[]) => ({
  ...IDENTITY,
  permissions: [],
  workspaces: [{ id: "ws-1", name: "Acme Corp", role: "member", permissions }],
});

const card = (page: Page) => page.getByRole("heading", { name: "Get set up", level: 3 });
const restore = (page: Page) => page.getByRole("button", { name: "Show setup checklist again" });

test.describe("onboarding steps the identity cannot act on", () => {
  test("a role that may neither invite nor mint keys has no card to complete", async ({ page }) => {
    const { cardCalls, failures } = watchCardRequests(page);
    await mockApi(page, {
      signedIn: true,
      identity: asRole(["member:read"]),
      // The data says both steps are done anyway: the user still has nothing
      // they are allowed to do on the card.
      lists: { invitations: [{ id: "inv-1" }], "api-keys": [{ id: "key-1" }] },
    });
    await page.goto("/");

    // Guards the two assertions below against a page that never rendered.
    await expect(page.getByRole("heading", { name: "Acme Corp", level: 2 })).toBeVisible();
    await expect(card(page)).toHaveCount(0);
    await expect(restore(page)).toHaveCount(0);
    // Listing either resource needs a permission this role lacks, so the card
    // must not even ask: the fetch would come back 403.
    expect(cardCalls).toEqual([]);
    expect(failures).toEqual([]);
  });

  test("an inviter keeps the invite step and loses the key step", async ({ page }) => {
    const { cardCalls, failures } = watchCardRequests(page);
    await mockApi(page, {
      signedIn: true,
      identity: asRole(["member:read", "member:create"]),
    });
    await page.goto("/");

    await expect(card(page)).toBeVisible();
    await expect(page.getByRole("link", { name: "Invite" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Create key" })).toHaveCount(0);
    // `apikey:read` is absent too, so the count behind that step is not fetched.
    expect(cardCalls.filter((pathname) => pathname.endsWith("/api-keys"))).toEqual([]);
    expect(failures).toEqual([]);
  });

  test("the card disappears once the only permitted step is done", async ({ page }) => {
    const { failures } = watchCardRequests(page);
    await mockApi(page, {
      signedIn: true,
      identity: asRole(["member:read", "member:create"]),
      lists: { invitations: [{ id: "inv-1" }] },
    });
    await page.goto("/");

    // Progress is read over the permitted steps only, so this is reachable
    // even though the omitted key step has no key behind it.
    await expect(page.getByRole("heading", { name: "Acme Corp", level: 2 })).toBeVisible();
    await expect(card(page)).toHaveCount(0);
    expect(failures).toEqual([]);
  });

  test("minting keys without being able to read them is not a step", async ({ page }) => {
    const { cardCalls, failures } = watchCardRequests(page);
    await mockApi(page, {
      signedIn: true,
      identity: asRole(["apikey:create"]),
    });
    await page.goto("/");
    // `toHaveCount(0)` passes on its first poll, and the card's permissions
    // resolve over the network: without this an absent card would prove
    // nothing at all.
    await page.waitForLoadState("networkidle");

    // `apikey:create` alone has no keys to count against, and the count
    // request itself would come back 403, so the step is dropped.
    await expect(card(page)).toHaveCount(0);
    expect(cardCalls.filter((pathname) => pathname.endsWith("/api-keys"))).toEqual([]);
    expect(failures).toEqual([]);
  });

  test("a role that may do both keeps both steps, so the case above is not vacuous", async ({
    page,
  }) => {
    const { cardCalls, failures } = watchCardRequests(page);
    await mockApi(page, { signedIn: true, identity: asRole(["*"]) });
    await page.goto("/");

    // The control: workspace permissions do resolve, so an absent card in the
    // cases above is the permission answer and not a failed lookup.
    await expect(card(page)).toBeVisible();
    await expect(page.getByRole("link", { name: "Invite" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Create key" })).toBeVisible();
    expect(cardCalls.filter((pathname) => pathname.endsWith("/api-keys"))).not.toHaveLength(0);
    expect(cardCalls.filter((pathname) => pathname.endsWith("/invitations"))).not.toHaveLength(0);
    expect(failures).toEqual([]);
  });
});
