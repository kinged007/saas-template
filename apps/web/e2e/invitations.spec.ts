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

const row = (page: Page, email: string) => page.getByRole("row").filter({ hasText: email });
const deleteButton = (page: Page, email: string) => row(page, email).getByRole("button", { name: "Delete" });

/** A role that may invite (member:create) but may not revoke (member:delete). */
const inviter = {
  ...IDENTITY,
  workspaces: [{ id: "ws-1", name: "Acme Corp", role: "custom", permissions: ["member:read", "member:create"] }],
};

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
  test("Delete is hidden, not disabled, without member:delete", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: inviter });
    await invitations(page);
    await page.goto("/members");

    // The section itself follows member:create, which also gates the list.
    await expect(page.getByRole("heading", { name: "Invited members" })).toBeVisible();
    await expect(row(page, "expired@example.com").getByRole("button", { name: "Re-send" })).toBeVisible();
    // DELETE /invitations/{id} requires member:delete: offer nothing rather
    // than a button that can never fire.
    await expect(deleteButton(page, "live@example.com")).toHaveCount(0);
    await expect(deleteButton(page, "expired@example.com")).toHaveCount(0);
  });

  test("a role with member:delete gets Delete on the pending rows", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await invitations(page);
    await page.goto("/members");

    await expect(deleteButton(page, "live@example.com")).toBeEnabled();
    await expect(deleteButton(page, "accepted@example.com")).toHaveCount(0);
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

  test("the invite submit sends the resolved role and disarms on an unpicked one", async ({ page }) => {
    const ADMIN = { id: "r-admin", workspace_id: "ws-1", name: "Admin", permissions: [], system: true };
    const EDITOR = { id: "r-editor", workspace_id: "ws-1", name: "Editor", permissions: [], system: true };
    const sent: unknown[] = [];
    await mockApi(page, { signedIn: true, identity: inviter, lists: { roles: [ADMIN, EDITOR] } });
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

    await page.getByLabel("Email").fill("person@example.com");
    const invite = page.getByRole("button", { name: "Invite" });
    // No role picked: the submit stays disarmed.
    await expect(invite).toBeDisabled();

    await page.getByRole("combobox").click();
    await page.getByRole("option", { name: "Editor" }).click();
    await expect(invite).toBeEnabled();
    await invite.click();

    // The payload carries the resolved role, not the raw picker's state value.
    await expect.poll(() => sent).toEqual([
      { email: "person@example.com", role_id: EDITOR.id },
    ]);
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
  });
});