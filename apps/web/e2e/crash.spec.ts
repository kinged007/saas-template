import { expect, test } from "playwright/test";

import { boundaryCrash, mockApi } from "./harness";

/**
 * The ErrorBoundary absorbs a render crash and renders its own fallback, so a
 * spec's own assertion can pass on the right URL while the user stares at an
 * error screen. React 18 rethrows a caught error in dev, so `pageerror` happens
 * to cover this under the dev server and nothing else does.
 *
 * This spec crashes the dashboard on purpose and asserts what the shared guard
 * reads: the fallback is on screen, and the boundary recorded the component
 * stack on window.
 *
 * It runs on the bare `test` from playwright, without the guard fixture,
 * because this is the one run that is supposed to crash.
 */
test("a crash the ErrorBoundary absorbs is visible and recorded", async ({ page }) => {
  // The bell sheet iterates the notifications body, so a body that is not an
  // array crashes its render the way a wrong endpoint shape would.
  await mockApi(page, {
    signedIn: true,
    errors: [],
    bodies: { "/notifications": { detail: "not a list" } },
  });

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Something went wrong" })).toBeVisible();
  await expect.poll(() => boundaryCrash(page)).toBeDefined();
});
