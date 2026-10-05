import type { Page } from "playwright/test";

export const IDENTITY = {
  id: "user-1",
  email: "e2e@example.com",
  first_name: "E2E",
  last_name: "User",
  is_superuser: true,
  permissions: ["*"],
  workspaces: [{ id: "ws-1", name: "Acme Corp", role: "owner" }],
  single_workspace: true,
};

export const ACCESS_TOKEN = [
  btoa(JSON.stringify({ alg: "HS256", typ: "JWT" })),
  btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600, sub: "user-1" })),
  "sig",
].join(".");

/**
 * Fulfill every backend call so the app runs with no API process. The session
 * endpoints decide auth; the list endpoints must answer with a bare array
 * (@refinedev/simple-rest maps the body straight to `data`); `/auth/config`
 * must report registration_enabled, or RegisterPage bounces to /login.
 *
 * The returned `signIn()` flips the mocked session mid-test, for flows that
 * start signed out and end signed in (the sign-in round trip). Specs that do
 * not need it ignore the return value.
 */
export async function mockApi(
  page: Page,
  {
    signedIn,
    identity = IDENTITY,
    lists = {},
  }: {
    signedIn: boolean;
    identity?: unknown;
    /** Rows for a bare `/api/v1/<resource>` list call; every other list answers `[]`. */
    lists?: Record<string, unknown[]>;
  },
) {
  const session = { signedIn };
  await page.route("**/api/v1/**", async (route) => {
    const reply = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    const { pathname } = new URL(route.request().url());
    if (pathname.endsWith("/auth/refresh")) {
      if (!session.signedIn) return reply(401, { detail: "No refresh token" });
      return reply(200, { access_token: ACCESS_TOKEN, token_type: "bearer" });
    }
    if (pathname.endsWith("/auth/me")) {
      if (!session.signedIn) return reply(401, { detail: "Not authenticated" });
      return reply(200, identity);
    }
    if (pathname.endsWith("/auth/oauth/token")) {
      // The exchange is what establishes the session, so the /auth/me the
      // callback page sends next is already authenticated.
      session.signedIn = true;
      return reply(200, { access_token: ACCESS_TOKEN, token_type: "bearer" });
    }
    if (pathname.endsWith("/auth/config")) {
      return reply(200, {
        registration_enabled: true,
        password_enabled: true,
        oauth_enabled: false,
        providers: [],
      });
    }
    if (pathname.endsWith("/auth/logout")) return route.fulfill({ status: 204, body: "" });
    const resource = pathname.slice("/api/v1/".length);
    // Own-property only: `in` walks Object.prototype, so `toString` would serve
    // `JSON.stringify` of an inherited function, which is undefined. `Object.hasOwn`
    // needs lib ES2022; tsconfig pins ES2020.
    if (Object.prototype.hasOwnProperty.call(lists, resource)) return reply(200, lists[resource]);
    return reply(200, []);
  });
  // The auth check only refreshes when the signed-in marker is set, so seed it
  // before any app code runs.
  await page.addInitScript(
    ({ hasSession }) => window.localStorage.setItem("tf_has_session", hasSession ? "1" : "0"),
    { hasSession: signedIn },
  );
  return { signIn: () => void (session.signedIn = true) };
}
