import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * The sidebar switcher reads `single_workspace` off /auth/me and renders the
 * workspace name as plain text when the flag is set, as a picker when it is
 * not. Both branches must survive AppLayout passing the flag down as a prop.
 *
 * Every assertion is scoped to the sidebar header: the dashboard names the
 * same workspace, so a page-global query matches whichever element comes first
 * in the DOM instead of the switcher.
 */
test.describe("workspace switcher", () => {
  const header = (page: Page) => page.locator('[data-sidebar="header"]');
  const TWO_WORKSPACES = [
    { id: "ws-1", name: "Acme Corp", slug: "acme-corp", role: "owner" },
    { id: "ws-2", name: "Beta Corp", slug: "beta-corp", role: "member" },
  ];

  test("single-workspace mode shows the name without a picker", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: { ...IDENTITY, single_workspace: true } });
    await page.goto("/");

    await expect(header(page).getByRole("combobox")).toHaveCount(0);
    await expect(header(page).getByText("Acme Corp")).toBeVisible();
  });

  test("multi-workspace mode shows a picker holding the name", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: { ...IDENTITY, single_workspace: false } });
    await page.goto("/");

    const trigger = header(page).getByRole("combobox");
    await expect(trigger).toBeVisible();
    await expect(trigger).toContainText("Acme Corp");
  });

  test("no workspace renders neither a picker nor a name", async ({ page }) => {
    await mockApi(page, {
      signedIn: true,
      identity: { ...IDENTITY, single_workspace: false, workspaces: [] },
    });
    await page.goto("/");

    await expect(page.getByText("You're not a member of any workspace yet.")).toBeVisible();
    await expect(header(page).getByRole("combobox")).toHaveCount(0);
    await expect(header(page).getByText("Acme Corp")).toHaveCount(0);
  });

  test("picking another workspace commits the selection", async ({ page }) => {
    await mockApi(page, {
      signedIn: true,
      identity: { ...IDENTITY, single_workspace: false, workspaces: TWO_WORKSPACES },
    });
    await page.goto("/");

    const trigger = header(page).getByRole("combobox");
    await trigger.click();
    await page.getByRole("option", { name: /Beta Corp/ }).click();
    await expect(trigger).toContainText("Beta Corp");
  });

  test("the create item routes to the create page", async ({ page }) => {
    await mockApi(page, {
      signedIn: true,
      identity: { ...IDENTITY, single_workspace: false, workspaces: TWO_WORKSPACES },
    });
    await page.goto("/");

    const trigger = header(page).getByRole("combobox");
    await trigger.click();
    await page.getByRole("option", { name: /Create new workspace/ }).click();
    await expect.poll(() => new URL(page.url()).pathname).toBe("/workspaces/create");
  });
});
