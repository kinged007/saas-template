import { expect, test as base, type Page } from "playwright/test";

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

const test = base.extend<{ pageerrors: Error[] }>({
  pageerrors: [
    async ({ page }, use) => {
      const errors: Error[] = [];
      page.on("pageerror", (error) => errors.push(error));
      await use(errors);
      expect(errors).toEqual([]);
    },
    { auto: true },
  ],
});

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
});