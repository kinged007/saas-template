import { expect } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The mock is the only backend the specs get, so its list matcher decides what
 * every unseeded resource answers. `in` would walk Object.prototype and serve
 * `JSON.stringify` of an inherited function, which is undefined.
 */
test.describe("mock-api list matching", () => {
  const get = (page: Parameters<typeof mockApi>[0], resource: string) =>
    page.evaluate(async (path) => {
      const response = await fetch(`/api/v1/${path}`);
      return { status: response.status, text: await response.text() };
    }, resource);

  test("a prototype key answers an empty list", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/login");
    expect(await get(page, "toString")).toEqual({ status: 200, text: "[]" });
  });

  test("a falsy seed is served as written", async ({ page }) => {
    await mockApi(page, { signedIn: true, lists: { conversations: "" as unknown as [] } });
    await page.goto("/login");
    expect(await get(page, "conversations")).toEqual({ status: 200, text: '""' });
  });
});
