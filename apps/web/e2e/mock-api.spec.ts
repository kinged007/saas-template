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

// The list total simple-rest reads: a header assertion needs `headers`, which
// the matcher above deliberately ignores.
const getList = async (page: Parameters<typeof mockApi>[0], resource: string, query = "") => {
  await page.goto("/verify-email");
  return page.evaluate(
    async ({ path }) => {
      const res = await fetch(path);
      return {
        status: res.status,
        text: await res.text(),
        total: res.headers.get("x-total-count"),
      };
    },
    { path: `/api/v1/${resource}${query}` },
  );
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

test("a list seed answers its length as x-total-count", async ({ page }) => {
  const roles = Array.from({ length: 105 }, (_, i) => ({ id: String(i + 1) }));
  await mockApi(page, { signedIn: true, lists: { roles } });
  expect(await getList(page, "roles")).toEqual({
    status: 200,
    text: JSON.stringify(roles),
    total: "105",
  });
});

test("an unseeded list answers an empty array with a zero total", async ({ page }) => {
  await mockApi(page, { signedIn: true });
  expect(await getList(page, "roles")).toEqual({ status: 200, text: "[]", total: "0" });
});

test("a seed longer than the requested window answers that page", async ({ page }) => {
  const roles = Array.from({ length: 105 }, (_, i) => ({ id: String(i + 1) }));
  await mockApi(page, { signedIn: true, lists: { roles } });
  const res = await getList(page, "roles", "?_start=0&_end=100");
  expect(res.status).toEqual(200);
  // The page is the window, but the total stays the fixture's length.
  expect(res.total).toEqual("105");
  expect((JSON.parse(res.text) as unknown[]).length).toEqual(100);
});
