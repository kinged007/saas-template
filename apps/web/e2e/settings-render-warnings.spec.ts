import { expect } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * `/settings/workspace/general` must not log `Cannot update a component while
 * rendering a different component`. The transfer block's truncated empty state
 * (no eligible member in the loaded window) is the state the warning was
 * reported against; the assertion is what locks the cross-component write out
 * of `WorkspaceProvider`'s identity subscription in `WorkspaceContext.tsx`.
 *
 * The seeded `tf_identity` is what puts the two renders in one pass: the
 * provider paints the stored identity on its first render while `/auth/me` is
 * still in flight, then re-renders from the cache the moment the fetch lands,
 * and the re-render re-sets up the identity observer mid-render.
 *
 * The sibling test pins the direction #1180 must not break: the same condition
 * suppresses no-op cache chatter, not genuine changes, so a seeded identity is
 * swapped for a different one over `/auth/me` and the sidebar must follow it.
 */

const identity = {
  id: "user-1",
  email: "owner@example.com",
  display_name: "Owner",
  is_superuser: false,
  permissions: ["*"],
  workspaces: [{ id: "ws-1", name: "Acme Corp", slug: "acme-corp", role: "owner" }],
  // The danger zone holding the transfer block is hidden on a single-workspace
  // account, so the zone under test would never render without this.
  single_workspace: false,
};

/** 100 loaded rows, none of them eligible (all owners), out of 124 members. */
const members = Array.from({ length: 100 }, (_, i) => ({
  id: `user-${i}`,
  email: `m${i}@example.com`,
  display_name: `M${i}`,
  first_name: `M${i}`,
  last_name: "Member",
  membership_id: `mem-${i}`,
  role_id: "1",
  role: "owner",
  status: "active",
  joined_at: "2026-01-01T00:00:00Z",
}));

test("the truncated empty state writes no state across components", async ({ page }) => {
  const crossComponentWrites: string[] = [];
  page.on("console", async (msg) => {
    if (!/Cannot update a component/.test(msg.text())) return;
    // React logs the component names as separate console args behind a `%s`
    // format string, so `msg.text()` still carries the placeholders. Resolve
    // every arg and join, so a captured write names the component pair instead
    // of an opaque template.
    const parts = await Promise.all(msg.args().map((arg) => arg.jsonValue()));
    crossComponentWrites.push(parts.join(" "));
  });
  await page.addInitScript(
    (seed) => window.localStorage.setItem("tf_identity", JSON.stringify(seed)),
    identity,
  );
  await mockApi(page, { signedIn: true, identity });

  // Gate on the /auth/me fetch the assertion measures, not only on the
  // empty-state anchors: the transfer state renders once that fetch resolves
  // (the workspace-settings layout waits on the identity query), but awaiting
  // the response explicitly keeps the assertion non-vacuous if that gate ever
  // moves. Served by mockApi, so this waits for the response rather than
  // holding it — holding it would block the settings layout from mounting the
  // section the anchors assert on.
  const authMeResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/api/v1/auth/me"),
  );

  await page.route(
    (url) => url.pathname.endsWith("/api/v1/members"),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "X-Total-Count": "124" },
        body: JSON.stringify(members),
      }),
  );

  await page.goto("/settings/workspace/general");
  // Anchors on the empty state itself: a page that never rendered it cannot
  // pass for the right reason.
  await expect(page.getByText("No eligible members in the 100 members loaded here")).toBeVisible();
  await expect(page.getByText("Showing the first 100 of 124 members")).toBeVisible();

  // The anchors appear once /auth/me has resolved (the settings layout waits on
  // the identity query before mounting this section); awaiting the captured
  // response makes that timing contract explicit so the assertion below cannot
  // run before the fetch the test is measuring.
  await authMeResponse;

  // Match the component pair, not every cross-component write: an unrelated
  // warning elsewhere on the page must not fail this test pointing at the
  // provider, and the resolved message names the pair so a real failure reads
  // as which components instead of an opaque template.
  expect(
    crossComponentWrites.filter(
      (write) => /WorkspaceProvider/.test(write) && /GeneralSection/.test(write),
    ),
  ).toEqual([]);
});

test("a genuine identity change still propagates to the provider", async ({ page }) => {
  // #1180 suppresses no-op identity-cache chatter; it must not stop the provider
  // re-rendering when the identity cache genuinely changes. The provider settles
  // on the seeded workspace while `/auth/me` is held, then a different identity
  // is delivered. The session token is already set by then, so no token-driven
  // re-render can mask a stalled subscription: reaching the served workspace
  // depends on the provider's identity subscription firing on the real cache
  // change. A suppressed subscription leaves the sidebar on the seeded workspace
  // — the stale-workspace bug this guards against.
  const servedIdentity: typeof identity = {
    ...identity,
    workspaces: [{ id: "ws-2", name: "Globex Corp", slug: "globex-corp", role: "owner" }],
  };
  await page.addInitScript(
    (seed) => window.localStorage.setItem("tf_identity", JSON.stringify(seed)),
    identity,
  );
  await mockApi(page, { signedIn: true });
  // Hold `/auth/me` until the provider has painted the seeded workspace, so the
  // served identity is a late change the subscription alone can deliver.
  // Registered after mockApi's `**/api/v1/**` catch-all, so last-registered-wins
  // routes `/auth/me` here.
  let releaseAuthMe!: () => void;
  const authMeHeld = new Promise<void>((resolve) => {
    releaseAuthMe = resolve;
  });
  await page.route((url) => url.pathname.endsWith("/api/v1/auth/me"), async (route) => {
    await authMeHeld;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(servedIdentity),
    });
  });

  await page.goto("/");
  const switcher = page.getByRole("combobox").first();
  // Settled on the seeded workspace before the change is delivered — holding
  // `/auth/me` keeps the provider on the stored identity.
  await expect(switcher).toContainText("Acme Corp");
  releaseAuthMe();
  // The sidebar switcher must follow the provider to the served workspace.
  await expect(switcher).toContainText("Globex Corp");
});
