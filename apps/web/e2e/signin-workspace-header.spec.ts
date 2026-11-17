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
 * login and register POST through raw fetch with a fixed header set, so the two
 * paths that go through httpClient are covered here: the 2FA verify POST and the
 * OAuth code exchange.
 *
 * Every API call is mocked, so no backend (and no DATABASE_URL) is needed.
 */
const OUTGOING_USER = "user-outgoing";
const OUTGOING_WORKSPACE = "ws-outgoing";

const path = (page: Page) => expect.poll(() => new URL(page.url()).pathname);

/**
 * A previous sign-in left its workspace selection in localStorage. Nothing has
 * hydrated it into memory, which is exactly the cold-load shape the
 * interceptor's store fallback exists for.
 */
function seedOutgoingSelection(page: Page) {
  return page.addInitScript(
    ({ userId, workspaceId }) => {
      window.localStorage.setItem(
        "tf_identity",
        JSON.stringify({ id: userId, email: "outgoing@example.com", workspaces: [] }),
      );
      window.localStorage.setItem(`tf_workspace_id:${userId}`, workspaceId);
    },
    { userId: OUTGOING_USER, workspaceId: OUTGOING_WORKSPACE },
  );
}

function recordAuthRequests(page: Page) {
  const authRequests: { path: string; workspace: string | undefined }[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/v1/auth/")) {
      authRequests.push({ path: url.pathname, workspace: request.headers()["x-workspace-id"] });
    }
  });
  return authRequests;
}

/**
 * The credential POST carries no workspace header, and neither does anything
 * after it in the round trip. Boot traffic before the sign-in was requested is
 * out of scope: nothing has signed out yet at that point.
 */
function expectNoOutgoingWorkspace(
  authRequests: { path: string; workspace: string | undefined }[],
  credentialPath: string,
) {
  const credentialPost = authRequests.findIndex((r) => r.path === credentialPath);
  expect(credentialPost).toBeGreaterThanOrEqual(0);
  expect(authRequests[credentialPost].workspace).toBeUndefined();
  expect(authRequests.slice(credentialPost).filter((r) => r.workspace === OUTGOING_WORKSPACE)).toEqual([]);
}

test.describe("sign-in credential requests", () => {
  test("the 2FA verify POST carries no workspace header from the outgoing session", async ({ page }) => {
    const api = await mockApi(page, { signedIn: false });
    await seedOutgoingSelection(page);
    const authRequests = recordAuthRequests(page);
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
    expectNoOutgoingWorkspace(authRequests, "/api/v1/auth/2fa/login");
  });

  test("the OAuth code exchange carries no workspace header from the outgoing session", async ({
    page,
  }) => {
    await mockApi(page, { signedIn: false });
    await seedOutgoingSelection(page);
    const authRequests = recordAuthRequests(page);

    await page.goto("/oauth/callback?code=code-123");

    // The exchange stores the access token and lands on the dashboard, so the
    // code was redeemed.
    await path(page).not.toBe("/oauth/callback");
    expectNoOutgoingWorkspace(authRequests, "/api/v1/auth/oauth/token");
    // The code is single-use: a second POST would race the first and report an
    // expired code, so exactly one exchange must leave the callback page.
    expect(authRequests.filter((r) => r.path === "/api/v1/auth/oauth/token")).toHaveLength(1);
  });
});
