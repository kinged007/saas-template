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
  page.on("console", (msg) => {
    if (/Cannot update a component/.test(msg.text())) crossComponentWrites.push(msg.text());
  });
  await page.addInitScript(
    (seed) => window.localStorage.setItem("tf_identity", JSON.stringify(seed)),
    identity,
  );
  await mockApi(page, { signedIn: true, identity });
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

  expect(crossComponentWrites).toEqual([]);
});
