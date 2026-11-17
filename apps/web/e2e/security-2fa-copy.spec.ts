import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * The setup-key copy button is icon-only and its icon flips to a check for 1.5 s
 * after the write — a purely visual confirmation. The announced one goes to a
 * visually hidden `role="status"` region next to the button (#1075): the button
 * keeps DOM focus across the copy, and a screen reader announces an
 * accessible-name change on a focused element only opportunistically, while
 * text entering a live region is announced reliably. So the button's
 * accessible name and `title` stay at "Copy setup key" in both states — a
 * button that reads "Copied" calls itself a status instead of a button. `title`
 * duplicates the accessible name (the pair #332 established).
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

/** The setup panel's live region: scoped by its text, so the page's other status regions don't collide. */
const confirmed = (page: Page) => page.getByRole("status").filter({ hasText: "Setup key copied" });

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

test("the setup-key copy button keeps its name and announces through the status region", async ({
  page,
}) => {
  await openSetupPanel(page);

  const copy = page.getByRole("button", { name: "Copy setup key", exact: true });
  await expect(copy).toHaveAccessibleName("Copy setup key");

  await copy.click();

  // The button keeps focus and its name — a name change on a focused element
  // is the announcement channel this suite must not rely on.
  await expect(copy).toBeFocused();
  await expect(copy).toHaveAccessibleName("Copy setup key");
  await expect(copy).toHaveAttribute("title", "Copy setup key");
  // The icon flip stays as the visual confirmation; the live region carries the
  // announced one.
  await expect(copy.locator("svg.lucide-check")).toBeVisible();
  await expect(confirmed(page)).toHaveCount(1);
});

test("a second click restarts the 1.5 s window", async ({ page }) => {
  await openSetupPanel(page);
  await freezePageTime(page);

  const copy = page.getByRole("button", { name: "Copy setup key", exact: true });
  await copy.click();
  await expect(confirmed(page)).toHaveCount(1);

  await page.clock.fastForward(1000);
  await copy.click();
  await expect(confirmed(page)).toHaveCount(1);

  // The first window ends here. A timer left over from the first click clears
  // the confirmation the second one owns; the second owns the whole 1.5 s.
  await page.clock.fastForward(500);
  await expect(confirmed(page)).toHaveCount(1);

  await page.clock.fastForward(1000);
  await expect(confirmed(page)).toHaveCount(0);
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

  // No live-region announcement: `copied` stays false, so the region stays
  // empty and the button never claims success; the fixture fails the test on
  // the unhandled rejection itself.
  const copy = page.getByRole("button", { name: "Copy setup key", exact: true });
  await copy.click();
  await expect(copy).toHaveAccessibleName("Copy setup key");
  await expect(confirmed(page)).toHaveCount(0);
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

  const copy = page.getByRole("button", { name: "Copy setup key", exact: true });
  await copy.click();
  await expect(confirmed(page)).toHaveCount(1);
  await copy.click();
  // Without a `setCopied(false)` in the catch the region keeps "Setup key
  // copied" forever: the second-click handler cleared the pending timer first.
  await expect(confirmed(page)).toHaveCount(0);
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

  const copy = page.getByRole("button", { name: "Copy setup key", exact: true });
  await copy.click();
  await expect(confirmed(page)).toHaveCount(1);

  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Set up authenticator" }).click();

  await expect(confirmed(page)).toHaveCount(0);
  await expect(copy).toHaveAccessibleName("Copy setup key");
});
