import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";
import { ACCESS_TOKEN, mockApi } from "./mock-api";

/**
 * The request that starts a sign-in must not carry the outgoing session's
 * workspace scope. The axios interceptor reads the active id synchronously and
 * falls back to `tf_identity` + `tf_workspace_id:<user>` in localStorage, so an
 * outgoing selection reaches the wire even on a cold page load with no
 * in-memory session.
 *
 * Exercised through the 2FA verify POST because that is the credential request
 * sent through httpClient; login and register POST through raw fetch with a
 * fixed header set, and the OAuth exchange needs a configured provider.
 *
 * Every API call is mocked, so no backend (and no DATABASE_URL) is needed.
 */
const OUTGOING_USER = "user-outgoing";
const OUTGOING_WORKSPACE = "ws-outgoing";

const path = (page: Page) => expect.poll(() => new URL(page.url()).pathname);

test.describe("sign-in credential requests", () => {
  test("the 2FA verify POST carries no workspace header from the outgoing session", async ({ page }) => {
    const api = await mockApi(page, { signedIn: false });
    // A previous sign-in left its workspace selection in localStorage. Nothing
    // has hydrated it into memory, which is exactly the cold-load shape the
    // interceptor's store fallback exists for.
    await page.addInitScript(
      ({ userId, workspaceId }) => {
        window.localStorage.setItem(
          "tf_identity",
          JSON.stringify({ id: userId, email: "outgoing@example.com", workspaces: [] }),
        );
        window.localStorage.setItem(`tf_workspace_id:${userId}`, workspaceId);
      },
      { userId: OUTGOING_USER, workspaceId: OUTGOING_WORKSPACE },
    );
    const authRequests: { path: string; workspace: string | undefined }[] = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/api/v1/auth/")) {
        authRequests.push({ path: url.pathname, workspace: request.headers()["x-workspace-id"] });
      }
    });
    // Registered after mockApi, so it takes precedence over its catch-all.
    await page.route("**/api/v1/auth/2fa/login", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ access_token: ACCESS_TOKEN, token_type: "bearer" }),
      }),
    );

    await page.goto("/login?challenge=chal-123");
    await path(page).toBe("/login");
    // The verify POST and the /auth/me it is followed by both need a session.
    api.signIn();
    await page.getByLabel("Two-factor code").fill("123456");
    await page.getByRole("button", { name: "Verify" }).click();

    await path(page).not.toBe("/login");
    // The credential POST and everything it is followed by — the outgoing
    // workspace must not be back on the wire during the sign-in round trip.
    // Boot traffic before the form was submitted is out of scope: nothing has
    // signed out yet at that point.
    const credentialPost = authRequests.findIndex((r) => r.path === "/api/v1/auth/2fa/login");
    expect(credentialPost).toBeGreaterThanOrEqual(0);
    expect(authRequests[credentialPost].workspace).toBeUndefined();
    expect(authRequests.slice(credentialPost).filter((r) => r.workspace === OUTGOING_WORKSPACE)).toEqual([]);
  });
});
