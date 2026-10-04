import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The API calls a role the owner role when its name is `owner` in any case
 * (`is_owner_role_name`, `apps/api/src/services/workspaces.py`) and admits a
 * manager when its name is `owner` or `admin` in any case
 * (`is_manager_role_name`). A pre-#328 workspace can hold rows spelled `Owner`,
 * and the UI has to reach the same verdict: offering a control the API refuses
 * with 409, or hiding one it would allow, is a wrong affordance.
 *
 * Every test anchors on something that must render before it reads an absence:
 * a page that has not rendered yet has no control of either kind, so counting
 * first would pass for the wrong reason.
 */

const role = (id: string, name: string) => ({
  id,
  workspace_id: "ws-1",
  name,
  permissions: [],
  system: false,
});

const member = (email: string, roleId: string, roleName: string) => ({
  id: `user-${roleId}`,
  email,
  display_name: roleName,
  first_name: roleName,
  last_name: "Member",
  membership_id: `mem-${roleId}`,
  role_id: roleId,
  role: roleName,
  status: "active",
  joined_at: "2026-01-01T00:00:00Z",
});

/**
 * A manager identity holding neither `"*"` nor superuser: both short-circuit
 * every `useCan` on the page, so the gates under test would pass or fail for
 * the wrong reason. `singleWorkspace` is on by default because the workspace
 * settings page is only reachable on a single-workspace account; the danger
 * zone that holds the transfer block needs it off.
 */
const identity = (myRole: string, { singleWorkspace = true } = {}) => ({
  id: "user-1",
  email: "manager@example.com",
  first_name: "Manager",
  is_superuser: false,
  permissions: [
    "member:read",
    "member:update",
    "member:delete",
    "member:create",
    "role:read",
    "role:create",
  ],
  workspaces: [{ id: "ws-1", name: "Acme Corp", role: myRole }],
  single_workspace: singleWorkspace,
});

const roles = (page: Page, rows: unknown[]) =>
  page.route(
    (url) => url.pathname.endsWith("/api/v1/roles"),
    (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rows) }),
  );

const members = (page: Page, rows: unknown[]) =>
  page.route(
    (url) => url.pathname.endsWith("/api/v1/members"),
    (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(rows) }),
  );

const row = (page: Page, email: string) => page.getByRole("row").filter({ hasText: email });

test.describe("owner role named in another case", () => {
  test("an `Owner` member row is offered no control the API refuses", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: identity("owner") });
    await members(page, [
      member("owner@example.com", "1", "Owner"),
      member("admin@example.com", "2", "admin"),
    ]);
    await roles(page, [role("1", "Owner"), role("2", "admin")]);
    await page.goto("/members");

    const ownerRow = row(page, "owner@example.com");
    const adminRow = row(page, "admin@example.com");
    await expect(ownerRow).toBeVisible();
    // The same viewer keeps full control over a non-owner row, so what is under
    // test is the owner name and not a page-wide lockout.
    await expect(adminRow.getByRole("combobox")).toBeVisible();
    await expect(adminRow.getByRole("button", { name: /suspend/i })).toBeVisible();
    await expect(adminRow.getByRole("button", { name: /delete/i })).toBeVisible();

    // set_member_role, suspend_member and remove_member each refuse the owner
    // with 409, so the row carries no combobox and no action button.
    await expect(ownerRow.getByRole("combobox")).toHaveCount(0);
    await expect(ownerRow.getByRole("button", { name: /suspend/i })).toHaveCount(0);
    await expect(ownerRow.getByRole("button", { name: /delete/i })).toHaveCount(0);
  });

  test("an `Owner` viewer still gets the role picker", async ({ page }) => {
    // is_manager_role_name folds the case, so the API admits this viewer; an
    // exact-case check on the client left the whole column as an em dash.
    await mockApi(page, { signedIn: true, identity: identity("Owner") });
    await members(page, [member("admin@example.com", "2", "admin")]);
    await roles(page, [role("1", "Owner"), role("2", "admin")]);
    await page.goto("/members");

    await expect(row(page, "admin@example.com").getByRole("combobox")).toBeVisible();
  });

  test("an `Owner` role row gets no edit control", async ({ page }) => {
    // update_role refuses the owner role with 403.
    await mockApi(page, { signedIn: true, identity: identity("owner") });
    await roles(page, [role("1", "Owner"), role("2", "admin")]);
    await page.goto("/settings/workspace/roles");

    await expect(page.getByRole("button", { name: "Edit admin" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit Owner" })).toHaveCount(0);
  });

  test("an `Owner` identity is offered Transfer ownership", async ({ page }) => {
    // Two gates hide this control and only one is under test: isOwnerRoleName
    // reads the viewer's own role, and transferEligibleMembers drops owner rows
    // so the owner is not offered as a target. A fixture with no other member
    // leaves the candidate list empty and the button absent for every identity,
    // so the active admin row here is what makes the owner gate observable.
    await mockApi(page, {
      signedIn: true,
      identity: identity("Owner", { singleWorkspace: false }),
    });
    await members(page, [
      member("owner@example.com", "1", "Owner"),
      member("admin@example.com", "2", "admin"),
    ]);
    await page.goto("/settings/workspace");

    await expect(page.getByRole("heading", { name: "Danger zone" })).toBeVisible();
    // The block renders for the folded owner name, and a candidate exists, so
    // the select and the button that needs it are both on the page.
    await expect(page.locator("#transfer-member")).toBeVisible();
    await expect(page.getByRole("button", { name: "Transfer ownership" })).toBeVisible();
  });

  test("an `admin` identity is offered no Transfer ownership", async ({ page }) => {
    // The mirror of the case above on the same block: the same two member rows,
    // so only the identity's role name differs. An empty candidate list would
    // leave the button absent either way and hide the case the pair tests.
    await mockApi(page, {
      signedIn: true,
      identity: identity("admin", { singleWorkspace: false }),
    });
    await members(page, [
      member("owner@example.com", "1", "Owner"),
      member("admin@example.com", "2", "admin"),
    ]);
    await page.goto("/settings/workspace");

    await expect(page.getByRole("heading", { name: "Danger zone" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Transfer ownership" })).toHaveCount(0);
  });
});
