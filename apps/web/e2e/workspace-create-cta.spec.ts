import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * With SINGLE_WORKSPACE on and the auto-join failed, /auth/me reports
 * single_workspace: true and no workspaces. /workspaces/create redirects home in
 * that mode, so a create affordance is a control that navigates nowhere.
 */
const lockedOut = { ...IDENTITY, single_workspace: true, workspaces: [] };

/** Identity for a user in zero workspaces who may still create one. */
const noWorkspaces = { ...IDENTITY, single_workspace: false, workspaces: [] };

/** Asserts on the pathname, so a redirect may add a query string. */
const path = (page: Page) => expect.poll(() => new URL(page.url()).pathname);

/** The copy the locked-out branch explains itself with. */
const ASK_AN_ADMIN = /ask an administrator/i;

test.describe("workspace create call to action", () => {
  test("single-workspace mode offers no way to create one", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: lockedOut });
    await page.goto("/");

    await expect(page.getByText("You're not a member of any workspace yet.")).toBeVisible();
    // Sidebar empty state (button) and the dashboard "No workspace yet" card
    // (link wrapped around a button) are both affordances for the same route.
    await expect(page.getByRole("button", { name: "Create workspace" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Create workspace" })).toHaveCount(0);
    // Zero affordances must still say why, not just stay empty.
    await expect(page.getByText(ASK_AN_ADMIN)).toBeVisible();
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

    await expect(page.getByText(ASK_AN_ADMIN)).toBeVisible();
    await expect(page.getByRole("button", { name: "Create workspace" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Create workspace" })).toHaveCount(0);
  });

  test("the button is still there when a workspace can be created", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: noWorkspaces });
    await page.goto("/");

    // The sidebar button and the dashboard link both render; .first() picks the
    // sidebar one out of the two matching buttons.
    await expect(page.getByRole("button", { name: "Create workspace" }).first()).toBeVisible();
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