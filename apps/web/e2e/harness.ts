import { expect, test as base, type Page } from "playwright/test";

/**
 * Shared fixtures and API mock for the e2e specs. Every backend call is
 * fulfilled here, so the suite runs against the vite dev server with no API
 * process and no database.
 */

/**
 * The component stack the app ErrorBoundary records on window when it catches
 * a crash (ErrorBoundary.componentDidCatch). `pageerror` covers this only
 * because React rethrows a caught error in dev; the flag is the contract that
 * holds in either build, and the fallback the user sees is a screen, not a
 * failed assertion.
 */
export const boundaryCrash = (page: Page) =>
  page.evaluate(() => (window as unknown as { __lastErrorStack?: string }).__lastErrorStack);

/**
 * Collects everything a green spec must not produce: an uncaught page error, a
 * crash the app ErrorBoundary absorbed, and an endpoint the mock does not
 * answer. Auto, so no spec can forget to assert it.
 */
export const test = base.extend<{ errors: Error[] }>({
  errors: [
    async ({ page }, use) => {
      const errors: Error[] = [];
      page.on("pageerror", (error) => errors.push(error));
      await use(errors);
      expect(errors, "the page must load without a crash").toEqual([]);
      expect(await boundaryCrash(page), "the ErrorBoundary absorbed a crash").toBeUndefined();
    },
    { auto: true },
  ],
});

const IDENTITY = {
  id: "user-1",
  email: "e2e@example.com",
  first_name: "E2E",
  last_name: "User",
  is_superuser: true,
  permissions: ["*"],
  workspaces: [{ id: "ws-1", name: "Acme Corp", role: "owner" }],
  single_workspace: true,
};

const PROFILE = {
  id: "profile-1",
  user_id: "user-1",
  display_name: "E2E User",
  email: "e2e@example.com",
  first_name: "E2E",
  last_name: "User",
  custom_data: {},
};

const ACCESS_TOKEN = [
  btoa(JSON.stringify({ alg: "HS256", typ: "JWT" })),
  btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600, sub: "user-1" })),
  "sig",
].join(".");

/**
 * The answer for every endpoint the pages under test call, keyed by URL
 * suffix. List endpoints must answer with a bare array (@refinedev/simple-rest
 * maps the body straight to `data`), which is also what makes a wrong shape a
 * crash rather than a blank page.
 */
const BODIES: Record<string, unknown> = {
  // the registration flag, or RegisterPage bounces to /login
  "/auth/config": {
    registration_enabled: true,
    password_enabled: true,
    oauth_enabled: false,
    providers: [],
  },
  // IDENTITY carries no profile, so the app fetches it
  "/me/profile": PROFILE,
  // the bell sheet and the badge counts in the app layout
  "/notifications": [],
  "/notifications/unread-count": { count: 0 },
  "/conversations/unread-count": { count: 0, unread_conversations: 0 },
  // the dashboard and the export card in workspace settings
  "/api-keys": [],
  "/members": [],
  // the data-export card lists what it can export
  "/workspaces/export/resources": { resources: ["members", "roles", "conversations"] },
  // the pending-invitations card in the app layout
  "/invitations": [],
};

type MockOptions = {
  /** The auth endpoints decide whether the app shows a page or the login form. */
  signedIn: boolean;
  /** The `errors` fixture, so an unmocked endpoint fails the spec. */
  errors: Error[];
  /** Suffix -> body, replacing the default answer. */
  bodies?: Record<string, unknown>;
};

/** Fulfill every backend call so the app runs with no API process. */
export async function mockApi(page: Page, { signedIn, errors, bodies }: MockOptions) {
  const table = { ...BODIES, ...bodies };
  await page.route("**/api/v1/**", async (route) => {
    const reply = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    const { pathname } = new URL(route.request().url());
    if (pathname.endsWith("/auth/refresh")) {
      if (!signedIn) return reply(401, { detail: "No refresh token" });
      return reply(200, { access_token: ACCESS_TOKEN, token_type: "bearer" });
    }
    if (pathname.endsWith("/auth/me")) {
      if (!signedIn) return reply(401, { detail: "Not authenticated" });
      return reply(200, IDENTITY);
    }
    if (pathname.endsWith("/auth/logout")) return route.fulfill({ status: 204, body: "" });
    const suffix = Object.keys(table).find((key) => pathname.endsWith(key));
    if (suffix) return reply(200, table[suffix]);
    // Fail closed. Answering [] here let an endpoint nobody mocked pass as an
    // empty list, so a new route or a paginated envelope surfaced as a crash
    // far from its cause instead of as a missing mock.
    const error = new Error(`unmocked: ${pathname}`);
    errors.push(error);
    throw error;
  });
  // The auth check only refreshes when the signed-in marker is set, so seed it
  // before any app code runs.
  await page.addInitScript(
    ({ hasSession }) => window.localStorage.setItem("tf_has_session", hasSession ? "1" : "0"),
    { hasSession: signedIn },
  );
}
