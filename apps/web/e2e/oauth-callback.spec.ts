import { expect, type Page } from "playwright/test";

import { OAUTH_CALLBACK_TIMEOUT_MS } from "../src/components/oauth-callback";
import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * `/auth/oauth/token` paths this page POSTed, in order — asserted as a count so
 * a path that stops sending (or sends twice — the code is single-use) shows up in
 * the test, not only in review.
 */
function recordTokenExchanges(page: Page) {
  const posts: string[] = [];
  page.on("request", (request) => {
    const { pathname } = new URL(request.url());
    if (pathname.endsWith("/auth/oauth/token")) posts.push(pathname);
  });
  return posts;
}

/** The OAuth callback page's terminal states must offer a way back to /login. */
test.describe("oauth callback escape", () => {
  test("missing code shows a link back to sign-in", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.goto("/oauth/callback");

    await expect(page.getByText("Missing sign-in code.")).toBeVisible();
    const link = page.getByRole("link", { name: "Back to sign-in" });
    await expect(link).toBeVisible();
    await link.click();
    await page.waitForURL(/\/login$/);
  });

  test("an error code shows a link that carries the error through to /login", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    await page.goto("/oauth/callback?error=invalid%20or%20expired%20state");

    await expect(page.getByText("Sign-in failed.")).toBeVisible();
    await page.getByRole("link", { name: "Back to sign-in" }).click();
    await page.waitForURL(/\/login\?error=/);
    // LoginPage renders the carried error back into the same message.
    await expect(page.getByText("Sign-in failed.")).toBeVisible();
  });

  test("the callback page keeps rendering while the identity settles", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    // Later handlers win over mockApi's catch-all: the /auth/me that
    // exchangeOAuthCode sends after the token lands never answers, so the
    // identity stays unsettled — exactly the window where the workspace gate
    // used to return null and unmount this page mid-exchange.
    await page.route("**/api/v1/auth/me", () => new Promise<void>(() => {}));

    await page.goto("/oauth/callback?code=code-123");
    // The token lands within milliseconds and (before the lift) the gate
    // blanks the page at that moment, so the pending state has to be checked
    // after that window, not during it.
    await page.waitForTimeout(2_000);
    await expect(page.getByText("Signing you in…")).toBeVisible();
  });

  test("a pending callback falls back to the escape once the timeout elapses", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    // Later handlers win over mockApi's catch-all: the exchange never answers,
    // so the page stays pending and only the timeout can end that state.
    await page.route("**/api/v1/auth/oauth/token", () => {});
    // runFor drives the page's own clock, so OAUTH_CALLBACK_TIMEOUT_MS crosses
    // here without paying 15s of wall clock in CI.
    await page.clock.install();
    const tokenPosts = recordTokenExchanges(page);

    await page.goto("/oauth/callback?code=code-123");

    await expect(page.getByText("Signing you in…")).toBeVisible();
    // The exchange really went out, so it is the timeout below that ends this page,
    // not a mount that never asked for the code at all.
    expect(tokenPosts).toHaveLength(1);
    // The escape belongs to the terminal states, so a pending page with a live
    // exchange shows nothing — asserting it now keeps the fallback honest.
    await expect(page.getByRole("link", { name: "Back to sign-in" })).toHaveCount(0);

    await page.clock.runFor(OAUTH_CALLBACK_TIMEOUT_MS);

    await expect(page.getByText("Sign-in is taking longer than expected.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to sign-in" })).toBeVisible();
  });

  test("a failed exchange drops its latch, so a repeat visit retries", async ({ page }) => {
    await mockApi(page, { signedIn: false });
    const tokenPosts = recordTokenExchanges(page);
    // Later handlers win over mockApi's catch-all: the code is refused, so the
    // callback lands in the terminal failure state. The latch is written
    // before the POST and cleared in its .catch — both halves are what this
    // test guards.
    await page.route("**/api/v1/auth/oauth/token", (route) =>
      route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({ detail: "invalid code" }),
      }),
    );

    await page.goto("/oauth/callback?code=code-123");
    await expect(page.getByText("Sign-in failed. The code may have expired.")).toBeVisible();
    expect(tokenPosts).toHaveLength(1);

    // Leave client-side and come back: the ?code= is still on the URL, and the
    // module latch outlives the navigate, so only the .catch's clear lets this
    // mount retry instead of returning silence from the guard and hanging on
    // "Signing you in…" with no error and no escape.
    await page.getByRole("link", { name: "Back to sign-in" }).click();
    await page.waitForURL(/\/login$/);
    // Gate on the committed unmount before going back: the click above and
    // goBack below are two history transitions ~50ms apart, and under load
    // React commits them as one — reconciling (not remounting) this page, so
    // the retry effect never re-runs and the stale failure DOM below passes
    // with one POST. A painted login proves the callback unmounted, which
    // makes goBack a real remount. Same-document transitions never touch the
    // back/forward cache, so goBack is safe here once the commit has landed.
    await expect(page.getByText("Sign in to your account")).toBeVisible();
    await page.goBack();

    await expect(page.getByText("Signing you in…")).toHaveCount(0);
    await expect(page.getByText("Sign-in failed. The code may have expired.")).toBeVisible();
    // Immediate, not polled: on a real remount the failure text is painted by
    // the .catch that follows the second POST, so a visible failure with one
    // POST means the remount never happened — exactly what this count guards.
    expect(tokenPosts).toHaveLength(2);
  });
});
