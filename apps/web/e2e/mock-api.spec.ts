import { expect } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The mock is the only backend the specs get, so its list matcher decides what
 * every unseeded resource answers. `in` would walk Object.prototype and serve
 * `JSON.stringify` of an inherited function, which is undefined.
 */
// The mock intercepts page requests only, so the fetch below must run in a page
// context (`page.request` bypasses `page.route`); the navigation exists only to
// supply an origin. `/verify-email` is outside every auth guard and never
// redirects, so nothing settles mid-`evaluate` and cancels the fetch.
const get = async (page: Parameters<typeof mockApi>[0], resource: string) => {
  await page.goto("/verify-email");
  return page.evaluate(async (path) => {
    const res = await fetch(path);
    return { status: res.status, text: await res.text() };
  }, `/api/v1/${resource}`);
};

test("a prototype key answers an empty list", async ({ page }) => {
  await mockApi(page, { signedIn: true });
  expect(await get(page, "toString")).toEqual({ status: 200, text: "[]" });
});

test("a falsy seed is served as written", async ({ page }) => {
  await mockApi(page, { signedIn: true, lists: { conversations: "" } });
  expect(await get(page, "conversations")).toEqual({ status: 200, text: '""' });
});

test("a defined own-property seed at __proto__ is served as written", async ({
  page,
}) => {
  // A literal `__proto__` key in an object literal sets the prototype, so the
  // own-property matcher below cannot see it; only a defined own property
  // reaches the branch the matcher is meant to exercise.
  const lists: Record<string, unknown> = {};
  Object.defineProperty(lists, "__proto__", {
    value: ["rows"],
    enumerable: true,
  });
  await mockApi(page, { signedIn: true, lists });
  expect(await get(page, "__proto__")).toEqual({ status: 200, text: '["rows"]' });
});
