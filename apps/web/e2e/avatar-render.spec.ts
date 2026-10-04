import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { ACCESS_TOKEN, IDENTITY, mockApi } from "./mock-api";

/**
 * Pins the stored-file avatar render path: `POST /files` returns the address of
 * a resource that needs a bearer token and X-Workspace-ID, so a browser <img>
 * cannot load it. useAvatarSrc fetches it with the app's client and hands
 * <AvatarImage> an object URL. Revert user-avatar.tsx to `getAvatarSrc` and every
 * other suite stays green while the avatar silently reverts to initials, so the
 * fetch itself is asserted here, not just the rendered pixels.
 */
const FILE_ID = "11111111-2222-3333-4444-555555555555";
const STORED_URL = `/api/v1/files/${FILE_ID}`;
const EXTERNAL_URL = "https://cdn.example.com/a.png";
// 1×1 opaque PNG: decodes, so naturalWidth proves the bytes arrived.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

/** The signed-in user's own avatar, in the sidebar user-menu trigger. */
const avatar = (page: Page) =>
  page.getByRole("button", { name: /e2e@example\.com/ }).locator("img");

const naturalWidth = (img: import("playwright/test").Locator) =>
  img.evaluate((el) => (el as HTMLImageElement).naturalWidth);

test.describe("stored-file avatars", () => {
  test("a stored file avatar_url renders as fetched bytes, not as a bare <img> src", async ({
    page,
  }) => {
    let auth: string | undefined;
    let workspace: string | undefined;
    await mockApi(page, { signedIn: true, identity: { ...IDENTITY, avatar_url: STORED_URL } });
    // Registered after the catch-all, so it wins for this path: Playwright runs
    // the most recently added matching route first.
    await page.route(`**/api/v1/files/${FILE_ID}`, async (route) => {
      const headers = await route.request().allHeaders();
      auth = headers.authorization;
      workspace = headers["x-workspace-id"];
      await route.fulfill({ status: 200, contentType: "image/png", body: PNG });
    });

    await page.goto("/");

    // blob: src = the bytes came through httpClient, not straight from the url.
    await expect(avatar(page)).toHaveAttribute("src", /^blob:/);
    expect(await naturalWidth(avatar(page))).toBe(1);
    // Both session headers reached the API; a plain <img> load sends neither.
    expect(auth).toBe(`Bearer ${ACCESS_TOKEN}`);
    expect(workspace).toBe("ws-1");
  });

  test("an external avatar_url is passed through and never carries the token", async ({
    page,
  }) => {
    let auth: string | undefined;
    await mockApi(page, {
      signedIn: true,
      identity: { ...IDENTITY, avatar_url: EXTERNAL_URL },
    });
    await page.route(EXTERNAL_URL, async (route) => {
      auth = (await route.request().allHeaders()).authorization;
      await route.fulfill({ status: 200, contentType: "image/png", body: PNG });
    });

    await page.goto("/");

    await expect(avatar(page)).toHaveAttribute("src", EXTERNAL_URL);
    expect(await naturalWidth(avatar(page))).toBe(1);
    expect(auth).toBeUndefined();
  });
});
