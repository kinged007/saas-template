import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * Regression tests for the invitations section of MembersPage. Every API call
 * is mocked, so these run against the dev server with no backend or database.
 */

const LIVE = {
  id: "inv-live",
  email: "live@example.com",
  status: "pending",
  expired: false,
  expires_at: "2099-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
};
const EXPIRED = {
  ...LIVE,
  id: "inv-expired",
  email: "expired@example.com",
  expired: true,
  expires_at: "2020-01-01T00:00:00Z",
};
const ACCEPTED = {
  ...LIVE,
  id: "inv-accepted",
  email: "accepted@example.com",
  status: "accepted",
};
const DECLINED = {
  ...LIVE,
  id: "inv-declined",
  email: "declined@example.com",
  status: "declined",
};
const REVOKED = {
  ...LIVE,
  id: "inv-revoked",
  email: "revoked@example.com",
  status: "revoked",
};
const EXPIRED_STATUS = {
  ...LIVE,
  id: "inv-expired-status",
  email: "expired-status@example.com",
  status: "expired",
};

const row = (page: Page, email: string) => page.getByRole("row").filter({ hasText: email });
const deleteButton = (page: Page, email: string) => row(page, email).getByRole("button", { name: "Delete" });
const resendButton = (page: Page, email: string) =>
  row(page, email).getByRole("button", { name: "Re-send" });

/**
 * A workspace actor claiming nothing itself. `IDENTITY` is superuser with a
 * `"*"` wildcard, and either short-circuit every `useCan`, so an actor that
 * inherits them passes a negative assertion for the wrong reason. Each actor
 * below names the permissions its test needs and only those.
 */
const actor = (permissions: string[], role = "admin") => ({
  ...IDENTITY,
  is_superuser: false,
  permissions: [],
  workspaces: [{ id: "ws-1", name: "Acme Corp", slug: "acme-corp", role, permissions }],
});

// May invite (member:create) and re-send but not revoke: DELETE
// /invitations/{id} requires member:delete. The owner/admin role name and
// member:update are what the row actions require — `resend_invitation` refuses
// any other actor with 403, and MembersPage gates both row controls on that
// same pair.
const manager = actor(["member:read", "member:create", "member:update"]);

// The invite form's actor: member:create gates the section, and the roles
// query behind the picker is ungated.
const inviteFormActor = actor(["member:read", "member:create"]);

// Every permission the manager holds, under a role name that is neither owner
// nor admin.
const customManager = actor(["member:read", "member:create", "member:update"], "custom");

// A route registered after mockApi takes precedence over its catch-all.
const invitations = (page: Page) =>
  page.route(
    (url) => url.pathname.endsWith("/api/v1/invitations"),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([LIVE, EXPIRED, ACCEPTED]),
      }),
  );

test.describe("invitations", () => {
  test("the negative actor carries neither superuser nor a wildcard", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: manager });
    await page.goto("/members");

    // A negative assertion in this file only means something if the actor it
    // runs under holds nothing at the top level: superuser and `"*"` both
    // short-circuit every `useCan`, so a gate would answer for a reason other
    // than the one under test.
    const identity = (await page.evaluate(() =>
      fetch("/api/v1/auth/me").then((response) => response.json()),
    )) as { is_superuser: boolean; permissions: string[] };
    expect(identity.is_superuser).toBe(false);
    expect(identity.permissions).toEqual([]);
  });

  test("Delete is hidden, not disabled, without member:delete", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: manager });
    await invitations(page);
    await page.goto("/members");

    // The section itself follows member:create, which also gates the list.
    await expect(page.getByRole("heading", { name: "Invited members" })).toBeVisible();
    // Re-send is a manager action, so this actor is offered one control and not
    // the other: the missing Delete below is a per-action gate, not an empty
    // actions cell.
    await expect(row(page, "expired@example.com").getByRole("button", { name: "Re-send" })).toBeVisible();
    // DELETE /invitations/{id} requires member:delete: offer nothing rather
    // than a button that can never fire.
    await expect(deleteButton(page, "live@example.com")).toHaveCount(0);
    await expect(deleteButton(page, "expired@example.com")).toHaveCount(0);
  });

  test("member:update under a non-manager role name gets no Re-send", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: customManager });
    await invitations(page);
    await page.goto("/members");

    // The section itself follows member:create, which this actor holds, so the
    // row below is on the page and the absence is read off a rendered list.
    await expect(row(page, "expired@example.com")).toBeVisible();
    // canManageRoles is `useCan(members:edit) && isManagerRoleName(role)`:
    // member:update satisfies the first half and the role name fails the
    // second, which is the client mirror of the 403 `resend_invitation` returns
    // for this actor.
    await expect(row(page, "expired@example.com").getByRole("button", { name: "Re-send" })).toHaveCount(0);
  });

  test("a role with member:delete gets Delete on the pending rows", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await invitations(page);
    await page.goto("/members");

    await expect(deleteButton(page, "live@example.com")).toBeEnabled();
    await expect(deleteButton(page, "accepted@example.com")).toHaveCount(0);
  });

  test("the Delete/Re-send buttons follow the revoke/resend gates per state", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.route(
      (url) => url.pathname.endsWith("/api/v1/invitations"),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([LIVE, EXPIRED, DECLINED, ACCEPTED, REVOKED, EXPIRED_STATUS]),
        }),
    );
    await page.goto("/members");

    // Every absence below is read off a rendered row, not a missing one.
    for (const email of [
      "live@example.com",
      "expired@example.com",
      "declined@example.com",
      "accepted@example.com",
      "revoked@example.com",
      "expired-status@example.com",
    ]) {
      await expect(row(page, email)).toBeVisible();
    }

    // Delete maps to revoke: offered on a live invitation only
    // (canRevokeInvitation is `status === "pending"`).
    await expect(deleteButton(page, "live@example.com")).toBeVisible();
    await expect(deleteButton(page, "expired@example.com")).toBeVisible();
    await expect(deleteButton(page, "declined@example.com")).toHaveCount(0);
    await expect(deleteButton(page, "accepted@example.com")).toHaveCount(0);
    await expect(deleteButton(page, "revoked@example.com")).toHaveCount(0);
    await expect(deleteButton(page, "expired-status@example.com")).toHaveCount(0);

    // Re-send is offered on an expired pending row, a declined row, and a
    // literal expired row; a fresh pending row is a no-op server-side and the
    // terminal accepted/revoked rows are refused.
    await expect(resendButton(page, "live@example.com")).toHaveCount(0);
    await expect(resendButton(page, "expired@example.com")).toBeVisible();
    await expect(resendButton(page, "declined@example.com")).toBeVisible();
    await expect(resendButton(page, "accepted@example.com")).toHaveCount(0);
    await expect(resendButton(page, "revoked@example.com")).toHaveCount(0);
    await expect(resendButton(page, "expired-status@example.com")).toBeVisible();
  });

  test("the row controls are separated by a gap", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await invitations(page);
    await page.goto("/members");

    const del = await deleteButton(page, "expired@example.com").boundingBox();
    const resend = await row(page, "expired@example.com").getByRole("button", { name: "Re-send" }).boundingBox();
    expect(del).not.toBeNull();
    expect(resend).not.toBeNull();
    // Without the wrapper both controls render flush against each other.
    expect(resend!.x - (del!.x + del!.width)).toBeGreaterThan(0);
  });

  test("an expired pending invitation is badged expired, not pending", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await invitations(page);
    await page.goto("/members");

    await expect(row(page, "expired@example.com").getByText("expired", { exact: true })).toBeVisible();
    await expect(row(page, "live@example.com").getByText("pending", { exact: true })).toBeVisible();
  });

  test("an expired invitation badge is destructive, a pending one is not", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await invitations(page);
    await page.goto("/members");

    await expect(row(page, "expired@example.com").getByText("expired", { exact: true })).toHaveClass(/bg-destructive/);
    await expect(row(page, "live@example.com").getByText("pending", { exact: true })).not.toHaveClass(
      /bg-destructive/,
    );
  });

  test("the invite submit needs a role and posts the picked one", async ({ page }) => {
    const ADMIN = { id: "r-admin", workspace_id: "ws-1", name: "Admin", permissions: [], system: true };
    const EDITOR = { id: "r-editor", workspace_id: "ws-1", name: "Editor", permissions: [], system: true };
    const sent: unknown[] = [];
    await mockApi(page, { signedIn: true, identity: inviteFormActor, lists: { roles: [ADMIN, EDITOR] } });
    await page.route(
      (url) => url.pathname.endsWith("/api/v1/invitations"),
      async (route) => {
        if (route.request().method() === "POST") {
          sent.push(route.request().postDataJSON());
          return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: "inv-new" }) });
        }
        return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      },
    );
    await page.goto("/members");

    const form = page.locator("form");
    const role = form.getByRole("combobox");
    await page.getByLabel("Email").fill("person@example.com");
    const invite = form.getByRole("button", { name: "Invite" });
    // No role picked: the submit is disarmed and the trigger shows the placeholder.
    await expect(invite).toBeDisabled();
    await expect(role).toHaveText("Role");

    await role.click();
    await page.getByRole("option", { name: "Editor" }).click();
    await expect(role).toHaveText("Editor");
    await expect(invite).toBeEnabled();
    await invite.click();

    // Happy path only: both assertions also hold before the resolve-role gate,
    // which has no live trigger here (nothing invalidates the roles query). The
    // stale-id disarm is covered where it discriminates, in invite-role.test.ts.
    await expect.poll(() => sent).toEqual([{ email: "person@example.com", role_id: EDITOR.id }]);
  });

  test("a failed re-send refreshes the list, so the stale button cannot survive it", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    let revoked = false;
    await page.route(
      (url) => url.pathname.endsWith("/api/v1/invitations"),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            LIVE,
            revoked ? { ...EXPIRED, status: "revoked", expired: false } : EXPIRED,
            ACCEPTED,
          ]),
        }),
    );
    await page.route(
      (url) => url.pathname.endsWith("/api/v1/invitations/inv-expired/resend"),
      (route) => {
        revoked = true;
        return route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "invitation is revoked and cannot be re-sent; invite this address again",
          }),
        });
      },
    );
    await page.goto("/members");

    const resend = row(page, "expired@example.com").getByRole("button", { name: "Re-send" });
    await expect(resend).toBeVisible();
    await resend.click();

    // revoked is terminal server-side, so the refused click has to refresh the
    // cached list instead of leaving the button that made it.
    await expect(row(page, "expired@example.com").getByText("revoked", { exact: true })).toBeVisible();
    await expect(resend).toHaveCount(0);
    // The refusal must still be announced. The toast comes from refine's
    // hook-level onError (description carries the 409 detail), so it only
    // survives while the refresh handlers stay in the per-mutate() options:
    // hoisting them into useCustomMutation() would replace refine's handler and
    // silently drop the detail. The sonner Toaster section is the page's only
    // named live region; the toast <li> itself has no role.
    await expect(
      page
        .getByRole("region", { name: "Notifications alt+T" })
        .getByText(/cannot be re-sent/),
    ).toBeVisible();
  });
});
