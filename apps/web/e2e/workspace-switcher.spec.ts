import { expect } from "playwright/test";

import { test } from "./fixtures";
import { IDENTITY, mockApi } from "./mock-api";

/**
 * The sidebar switcher reads `single_workspace` off /auth/me and renders the
 * workspace name as plain text when the flag is set, as a picker when it is
 * not. Both branches must survive AppLayout passing the flag down as a prop.
 */
test.describe("workspace switcher", () => {
  test("single-workspace mode shows the name without a picker", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: { ...IDENTITY, single_workspace: true } });
    await page.goto("/");

    await expect(page.getByRole("combobox")).toHaveCount(0);
    await expect(page.getByText("Acme Corp").first()).toBeVisible();
  });

  test("multi-workspace mode shows a picker holding the name", async ({ page }) => {
    await mockApi(page, { signedIn: true, identity: { ...IDENTITY, single_workspace: false } });
    await page.goto("/");

    const trigger = page.getByRole("combobox").first();
    await expect(trigger).toBeVisible();
    await expect(trigger).toContainText("Acme Corp");
  });
});
