import { expect } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

const member = (id: string, name: string) => ({
  id: `user-${id}`,
  membership_id: `membership-${id}`,
  email: `${id}@example.com`,
  first_name: name,
  last_name: "Member",
  display_name: name,
  role_id: "role-admin",
  role: "admin",
  status: "active",
  joined_at: "2026-01-01T00:00:00Z",
});

test("ownership transfer rejects a removed selection and submits the current member's membership id", async ({ page }) => {
  const picked = member("picked", "Picked");
  const remaining = member("remaining", "Remaining");
  const lists = { members: [picked, remaining] };
  const submissions: unknown[] = [];
  await mockApi(page, {
    signedIn: true,
    identity: { ...IDENTITY, single_workspace: false },
    lists,
  });
  await page.route("**/api/v1/workspaces/ws-1/transfer", async (route) => {
    expect(route.request().method()).toBe("POST");
    submissions.push(route.request().postDataJSON());
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await page.goto("/settings/workspace");

  const select = page.getByRole("combobox", { name: "New owner" });
  const transfer = page.getByRole("button", { name: "Transfer ownership", exact: true });
  await expect(transfer).toBeDisabled();
  await select.click();
  await page.getByRole("option", { name: /picked@example.com/ }).click();
  await expect(select).toContainText("picked@example.com");
  await expect(transfer).toBeEnabled();
  await transfer.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("picked@example.com");

  lists.members = [remaining];
  // Reconnecting refetches the mounted query; a reload would erase the selection.
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  const refreshed = page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/api/v1/members" && response.status() === 200,
  );
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await refreshed;
  await expect(dialog).toHaveCount(0);
  await expect(transfer).toBeDisabled();
  await expect(select).toContainText("Select member");
  await transfer.evaluate((button: HTMLButtonElement) => button.click());
  expect(submissions).toEqual([]);

  await select.click();
  await expect(page.getByRole("option", { name: /picked@example.com/ })).toHaveCount(0);
  await page.getByRole("option", { name: /remaining@example.com/ }).click();
  await expect(transfer).toBeEnabled();
  await transfer.click();
  await expect(dialog).toContainText("remaining@example.com");
  await dialog.getByRole("button", { name: "Transfer ownership", exact: true }).click();
  await expect(page.getByText("Ownership transferred", { exact: true })).toBeVisible();
  expect(submissions).toEqual([{ new_owner_membership_id: remaining.membership_id }]);
});
