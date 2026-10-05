import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { mockApi } from "./mock-api";

/**
 * A deep link opened while signed out is denied by the `Authenticated` guard in
 * src/App.tsx. The guard records what was asked for in `tf_return_to`, and
 * afterAuthRedirect() replays it once sign-in succeeds.
 *
 * Every API call is mocked, so no backend (and no DATABASE_URL) is needed.
 */
const path = (page: Page) => expect.poll(() => new URL(page.url()).pathname);
const origin = (page: Page) => new URL(page.url()).origin;
const returnTo = (page: Page) => page.evaluate(() => window.localStorage.getItem("tf_return_to"));

const signIn = async (page: Page) => {
  await page.getByLabel("Email").fill("e2e@example.com");
  await page.getByLabel("Password").fill("Passw0rd!23");
  await page.getByRole("button", { name: "Sign in" }).click();
};

test.describe("sign-in return-to", () => {
  test("a deep link denied by the guard is recorded and replayed after sign-in", async ({ page }) => {
    const api = await mockApi(page, { signedIn: false });
    await page.goto("/api-keys?page=2");

    await path(page).toBe("/login");
    expect(await returnTo(page)).toBe("/api-keys?page=2");

    // The sign-in round trip starts signed out and ends signed in, so flip the
    // mock before submitting or the follow-up /auth/me answers 401 and the
    // interceptor bounces back to /login.
    api.signIn();
    await signIn(page);

    await page.waitForURL(/\/api-keys/);
    const url = new URL(page.url());
    expect(url.pathname).toBe("/api-keys");
    expect(url.search).toBe("?page=2");
    // Consumed once, so a second sign-in cannot replay a stale destination.
    expect(await returnTo(page)).toBeNull();
  });

  test("a pending invitation outranks a recorded destination", async ({ page }) => {
    const api = await mockApi(page, { signedIn: false });
    await page.goto("/api-keys?page=2");
    await path(page).toBe("/login");
    await page.evaluate(() => window.localStorage.setItem("tf_pending_invitation", "inv-token"));

    api.signIn();
    await signIn(page);

    await page.waitForURL(/\/invitations\/accept/);
    expect(new URL(page.url()).pathname).toBe("/invitations/accept");
    expect(new URL(page.url()).searchParams.get("token")).toBe("inv-token");
    // The loser must go too, or it fires at the next sign-in.
    expect(await returnTo(page)).toBeNull();
  });

  // Each destination a crafted link can record that the guard must refuse; why
  // it refuses them is documented once, on sameOriginPath. This table samples
  // the class for the browser path; sameOriginPath.test.ts pins the full list.
  for (const dest of [
    "//evil.example/x",
    "/\\evil.example/x",
    "/\tevil.example/x",
    "/\t/evil.example/x",
    "/\nevil.example/x",
    "/\revil.example/x",
  ]) {
    test(`a destination that only looks relative is dropped: ${JSON.stringify(dest)}`, async ({ page }) => {
      const api = await mockApi(page, { signedIn: false });
      await page.goto("/api-keys?page=2");
      await path(page).toBe("/login");
      const appOrigin = origin(page);
      await page.evaluate((d) => window.localStorage.setItem("tf_return_to", d), dest);

      api.signIn();
      await signIn(page);

      // One assertion on the full href pins origin and pathname together.
      await expect.poll(() => page.url()).toBe(`${appOrigin}/`);
      expect(await returnTo(page)).toBeNull();
    });
  }

  test("signing in converges on the destination instead of looping", async ({ page }) => {
    const api = await mockApi(page, { signedIn: false });
    const navs: string[] = [];
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame()) navs.push(frame.url());
    });

    await page.goto("/api-keys?page=2");
    await path(page).toBe("/login");
    api.signIn();
    await signIn(page);
    await page.waitForURL(/\/api-keys/);
    const settled = page.url();
    // Let any deferred guard render land before judging convergence.
    await page.waitForTimeout(1_000);

    expect(page.url()).toBe(settled);
    const isLogin = (u: string) => new URL(u).pathname === "/login";
    // A destination that rewrote itself would bounce back through /login.
    expect(navs.slice(navs.lastIndexOf(settled) + 1).filter(isLogin)).toEqual([]);
  });

  test("an explicit logout drops a recorded destination", async ({ page }) => {
    await mockApi(page, { signedIn: true });
    await page.goto("/");
    await page.evaluate(() => window.localStorage.setItem("tf_return_to", "/api-keys?page=2"));

    await page.getByRole("button", { name: /e2e@example\.com/ }).click();
    await page.getByRole("menuitem", { name: "Logout" }).click();

    await path(page).toBe("/login");
    expect(await returnTo(page)).toBeNull();
  });
});