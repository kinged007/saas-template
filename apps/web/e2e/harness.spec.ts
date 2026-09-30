import { expect, test as base } from "playwright/test";

import { mockApi } from "./harness";

/**
 * The mock fails closed: an endpoint it does not carry is an error, never a
 * permissive default. Answering `[]` for everything would let a spec pass on a
 * response shape the app never gets from the backend.
 *
 * It runs on the bare `test` from playwright, without the guard fixture, because
 * this is the one spec that is supposed to record an unmocked endpoint.
 */
base("an endpoint the mock does not answer is recorded instead of defaulted", async ({ page }) => {
  const errors: Error[] = [];
  await mockApi(page, { signedIn: true, errors });
  await page.goto("/");

  await page.evaluate(() => {
    void fetch("/api/v1/not-a-real-endpoint");
  });

  await expect
    .poll(() => errors.map((error) => error.message))
    .toContain("unmocked: /api/v1/not-a-real-endpoint");
});
