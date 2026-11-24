import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * SINGLE_WORKSPACE on and /auth/me reporting no memberships: either the
 * auto-join failed, or the user belongs to a workspace that is not the oldest
 * one and the flag hides it. Both produce the same response, so both must read
 * as "ask an administrator" — the UI cannot tell them apart, and in the second
 * case nothing is created for the user. /workspaces/create redirects home while
 * the flag is set, so a create affordance navigates nowhere.
 */
const lockedOut = { ...IDENTITY, single_workspace: true, workspaces: [] };

/** Identity for a user in zero workspaces who may still create one. */
const noWorkspaces = { ...IDENTITY, single_workspace: false, workspaces: [] };

/** Asserts on the pathname, so a redirect may add a query string. */
const path = (page: Page) => expect.poll(() => new URL(page.url()).pathname);

/** Sidebar copy when no workspace can be created; now the full locked-out sentence. */
const ASK_AN_ADMIN = "Ask an administrator to add you to it.";

/** The card's locked-out sentence, now also rendered by the sidebar. */
const LOCKED_OUT_CARD = "This deployment allows one workspace.";

/** The full locked-out sentence rendered by both the card and the sidebar. */
const LOCKED_OUT_FULL = `${LOCKED_OUT_CARD} ${ASK_AN_ADMIN}`;

test.describe("workspace create call to action", () => {
  test("single-workspace mode offers no way to create one", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: lockedOut });
    await page.goto("/");

    // Both the sidebar and the card render the full locked-out sentence.
    await expect(page.getByText(LOCKED_OUT_FULL)).toHaveCount(2);
    // Sidebar empty state (button) and the dashboard "No workspace yet" card
    // (a link) are both affordances for the same route.
    await expect(page.getByRole("button", { name: "Create workspace" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Create workspace" })).toHaveCount(0);
  });

  test("/settings/profile/workspaces offers the same create CTA", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: noWorkspaces });
    await page.goto("/settings/profile/workspaces");

    await expect(page.getByRole("link", { name: "Create workspace" })).toBeVisible();
    await expect(page.getByText("No workspaces yet.")).toHaveCount(0);
  });

  test("/settings/profile/workspaces explains a locked-out user", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: lockedOut });
    await page.goto("/settings/profile/workspaces");

    await expect(page.getByText(LOCKED_OUT_FULL)).toHaveCount(2);
    await expect(page.getByRole("button", { name: "Create workspace" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Create workspace" })).toHaveCount(0);
  });

  test("the profile list says nothing until the membership list settles", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: noWorkspaces });
    // Registered after mockApi, so it wins the match: the delay makes the
    // in-flight frame observable, which the instant mock never produces.
    await page.route(
      (url) => url.pathname === "/api/v1/workspaces",
      async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      },
    );
    await page.goto("/settings/profile/workspaces");

    // Identity resolved (the sidebar needs it) while the list is still in
    // flight: neither answer may be on screen yet.
    await expect(page.getByText("You're not a member of any workspace yet.")).toBeVisible();
    await expect(page.getByText("No workspaces yet.")).toHaveCount(0);
    await expect(page.getByText("No workspace yet")).toHaveCount(0);
    await expect(page.getByText("No workspace yet")).toBeVisible({ timeout: 10_000 });
  });

  test("the button is still there when a workspace can be created", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: noWorkspaces });
    await page.goto("/");

    // The sidebar renders a button and the card a link; strict mode fails if the
    // card nests a button in its link again.
    await expect(page.getByRole("button", { name: "Create workspace" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Create workspace" })).toBeVisible();
  });
});

/**
 * With zero workspaces nothing auto-selects, so useWorkspaceQuery keeps every
 * workspace-scoped query disabled: pages sit on `isPending` forever or render a
 * misleading empty list, and neither tells the user why. /App.tsx therefore
 * redirects the workspace-scoped routes to the dashboard, which already carries
 * the "No workspace yet" card and its CTA.
 */
test.describe("zero workspaces on a workspace-scoped route", () => {
  for (const url of [
    "/members",
    "/api-keys",
    "/api-keys/create",
    "/webhooks",
    "/webhooks/create",
    "/inbox",
    "/jobs/job-1",
    "/jobs/job-1/runs/run-1",
    "/settings/workspace",
    "/settings/workspace/users",
  ]) {
    test(`${url} lands on the dashboard instead of stalling`, async ({ page }) => {
      await mockApi(page, { signedIn: true, identity: noWorkspaces });
      await page.goto(url);
      await path(page).toBe("/");
      await expect(page.getByText("No workspace yet")).toBeVisible();
      await expect(page.getByRole("link", { name: "Create workspace" })).toBeVisible();
    });
  }

  test("a locked-out user is redirected with no create affordance", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: lockedOut });
    await page.goto("/inbox");
    await path(page).toBe("/");
    await expect(page.getByText("No workspace yet")).toBeVisible();
    await expect(page.getByRole("button", { name: "Create workspace" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Create workspace" })).toHaveCount(0);
  });

  // The next four fail if the guard is over-broad: these routes carry no
  // workspace data and the CTA has to reach /workspaces/create.
  test("/workspaces/create — the CTA target — stays reachable", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: noWorkspaces });
    await page.goto("/workspaces/create");
    await path(page).toBe("/workspaces/create");
    // Scoped to the form: the sidebar renders a button with the same name.
    await expect(
      page.locator("form").getByRole("button", { name: "Create workspace" }),
    ).toBeVisible();
  });

  test("/settings/profile/general stays reachable", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: noWorkspaces });
    await page.goto("/settings/profile/general");
    await path(page).toBe("/settings/profile/general");
    await expect(page.getByText("Personal Information", { exact: true })).toBeVisible();
  });

  test("/invitations stays reachable — accepting one grants the first workspace", async ({
    page,
  }) => {
    await mockApi(page, { signedIn: true, identity: noWorkspaces });
    await page.goto("/invitations");
    await path(page).toBe("/invitations");
  });

  test("/admin/users stays reachable", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: noWorkspaces });
    await page.goto("/admin/users");
    await path(page).toBe("/admin/users");
  });

  test("a user with a workspace is not redirected", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/api-keys");
    await path(page).toBe("/api-keys");
  });
});
