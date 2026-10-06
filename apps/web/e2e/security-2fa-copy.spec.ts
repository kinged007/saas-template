import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The setup-key copy button is icon-only and its icon flips to a check for 1.5 s
 * after the write, so the accessible name has to flip with it: a button that
 * still reads "Copy setup key" in the copied state announces the action the
 * user just performed instead of a confirmation. `title` duplicates the
 * accessible name (the pair #332 established), so the two are asserted equal.
 *
 * The confirmation clears itself after 1.5 s, so every read of it goes through
 * a retrying assertion on one handle — a one-shot read of a state that expires
 * mid-test is a flake, not a signal.
 *
 * Registered after `mockApi` on purpose — Playwright runs the most recently
 * added matching handler first, so only this one URL is intercepted here.
 */
const SETUP = {
  setup_token: "setup-1",
  otpauth_uri: "otpauth://totp/Acme:E2E?secret=JBSWY3DPEHPK3PXP&issuer=Acme",
  secret: "JBSWY3DPEHPK3PXP",
};

/** Matches the button in either state, so the handle survives the rename. */
const copyButton = (page: Page) => page.getByRole("button", { name: /^(Copy setup key|Copied)$/ });

/**
 * `install` fakes the page clock but leaves it running in real time, so a 1.5 s
 * window under test would still expire between two test statements. Pausing at
 * the page's own now leaves page time moving only when this test moves it — a
 * second past it, because reading the clock and pausing it are two round trips
 * and the page keeps ticking in between.
 */
const freezePageTime = async (page: Page) => {
  await page.clock.install();
  await page.clock.pauseAt(await page.evaluate(() => Date.now() + 1000));
};

/** Mocks the API and opens the setup panel with its QR code and key. */
async function openSetupPanel(page: Page) {
  // The handler awaits the clipboard write before it flips the icon, so a denied
  // write would fail the assertions below for the wrong reason.
  await page.context().grantPermissions(["clipboard-write"]);
  await mockApi(page, { signedIn: true });
  await page.route("**/api/v1/auth/2fa/setup", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(SETUP) }),
  );
  await page.goto("/settings/profile/security");
  await page.getByRole("button", { name: "Set up authenticator" }).click();
}

test("the setup-key copy button announces the copy, then the confirmation", async ({ page }) => {
  await openSetupPanel(page);

  const copy = copyButton(page);
  await expect(copy).toHaveAccessibleName("Copy setup key");

  await copy.click();

  // One handle, two retrying assertions: the name check covers the rename (the
  // old name no longer resolves), the attribute check covers #332's pair.
  await expect(copy).toHaveAccessibleName("Copied");
  await expect(copy).toHaveAttribute("title", "Copied");
});

test("a second click restarts the 1.5 s window", async ({ page }) => {
  await openSetupPanel(page);
  await freezePageTime(page);

  const copy = copyButton(page);
  await copy.click();
  await expect(copy).toHaveAccessibleName("Copied");

  await page.clock.fastForward(1000);
  await copy.click();
  await expect(copy).toHaveAccessibleName("Copied");

  // The first window ends here. A timer left over from the first click clears
  // the confirmation the second one owns; the second owns the whole 1.5 s.
  await page.clock.fastForward(500);
  await expect(copy).toHaveAccessibleName("Copied");

  await page.clock.fastForward(1000);
  await expect(copy).toHaveAccessibleName("Copy setup key");
});

test("a denied write toasts instead of claiming success", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window.navigator, "clipboard", {
      value: { writeText: () => Promise.reject(new Error("Denied")) },
      configurable: true,
    });
  });
  await openSetupPanel(page);

  // Unchanged name: `copied` stays false, so the button never claims success;
  // the fixture fails the test on the unhandled rejection itself.
  const copy = page.getByRole("button", { name: "Copy setup key", exact: true });
  await copy.click();
  await expect(copy).toHaveAccessibleName("Copy setup key");
  await expect
    .poll(async () => (await page.locator('section[aria-live="polite"]').textContent()) ?? "")
    .toMatch(/could not copy/i);
});

test("a denied second write clears the pending confirmation", async ({ page }) => {
  await page.addInitScript(() => {
    let calls = 0;
    Object.defineProperty(window.navigator, "clipboard", {
      value: {
        writeText: () => {
          calls += 1;
          return calls === 1 ? Promise.resolve() : Promise.reject(new Error("Denied"));
        },
      },
      configurable: true,
    });
  });
  await openSetupPanel(page);

  const copy = copyButton(page);
  await copy.click();
  await expect(copy).toHaveAccessibleName("Copied");
  await copy.click();
  // Without a `setCopied(false)` in the catch the button stays "Copied"
  // forever: the second-click handler cleared the pending timer first.
  await expect(copy).toHaveAccessibleName("Copy setup key");
  await expect
    .poll(async () => (await page.locator('section[aria-live="polite"]').textContent()) ?? "")
    .toMatch(/could not copy/i);
});

test("cancel drops the copy confirmation", async ({ page }) => {
  await openSetupPanel(page);
  // Frozen, or the pending reset runs on its own and a stale confirmation is
  // indistinguishable from one that expired in time.
  await freezePageTime(page);

  const copy = copyButton(page);
  await copy.click();
  await expect(copy).toHaveAccessibleName("Copied");

  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Set up authenticator" }).click();

  await expect(copy).toHaveAccessibleName("Copy setup key");
});
