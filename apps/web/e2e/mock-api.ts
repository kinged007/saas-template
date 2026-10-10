import type { Page } from "playwright/test";
import type { Identity } from "../src/types";

export const IDENTITY: Identity = {
  id: "user-1",
  email: "e2e@example.com",
  display_name: "E2E User",
  profile: {
    id: "profile-1",
    user_id: "user-1",
    first_name: "E2E",
    last_name: "User",
    custom_data: {},
  },
  is_superuser: true,
  permissions: ["*"],
  workspaces: [{ id: "ws-1", name: "Acme Corp", slug: "acme-corp", role: "owner" }],
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
    revokeOn = [],
  }: {
    signedIn: boolean;
    identity?: Identity;
    /** Rows for a bare `/api/v1/<resource>` list call; every other list answers `[]`. */
    lists?: Record<string, unknown[]>;
    /** Path suffixes answered 401 `{detail: "session revoked"}` once, then normal — mid-session sign-out. */
    revokeOn?: string[];
  },
) {
  const session = { signedIn };
  const revocations = new Set<string>();
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
    if (revokeOn.some((suffix) => pathname.endsWith(suffix))) {
      // One-shot: the replay after sign-in must get a 200 or the destination
      // page itself bounces straight back to /login.
      if (!revocations.has(pathname)) {
        // A revoked session is dead server-side too: flip the mock so the
        // /login boot after the bounce does not silently restore the session.
        session.signedIn = false;
        revocations.add(pathname);
        return reply(401, { detail: "session revoked" });
      }
    }
    const resource = pathname.slice("/api/v1/".length);
    // Own-property only: `in` walks Object.prototype, so `toString` would serve
    // `JSON.stringify` of an inherited function, which is undefined. `Object.hasOwn`
    // needs lib ES2022; tsconfig pins ES2020.
    if (Object.prototype.hasOwnProperty.call(lists, resource)) return reply(200, lists[resource]);
    return reply(200, []);
  });
  // The auth check only refreshes when the signed-in marker is set, so seed
  // it before any app code runs — ONCE: later loads must see the live marker
  // (forceLogout's clear or a sign-in's set), not a stale re-seed that would
  // silently restore a session the test flipped off.
  await page.addInitScript(
    ({ hasSession }) => {
      if (window.localStorage.getItem("tf_e2e_seeded") !== null) return;
      window.localStorage.setItem("tf_e2e_seeded", "1");
      window.localStorage.setItem("tf_has_session", hasSession ? "1" : "0");
    },
    { hasSession: signedIn },
  );
  return { signIn: () => void (session.signedIn = true) };
}

/**
 * Same session mocks with the two 2FA endpoints added: password sign-in is
 * answered with a `2fa_required` challenge and `/auth/2fa/login` accepts any
 * code and establishes the session. Separate from `mockApi` because its route
 * for `/auth/login` would turn the plain sign-in helper into a challenge loop.
 */
export async function mockApiTwoFactor(
  page: Page,
  { signedIn, revokeOn = [] }: { signedIn: boolean; revokeOn?: string[] },
) {
  const session = { signedIn };
  const revocations = new Set<string>();
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
      return reply(200, IDENTITY);
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
    if (revokeOn.some((suffix) => pathname.endsWith(suffix)) && !revocations.has(pathname)) {
      session.signedIn = false;
      revocations.add(pathname);
      return reply(401, { detail: "session revoked" });
    }
    return reply(200, []);
  });
  // Password sign-in challenges 2FA; the verify call establishes the session.
  await page.route("**/api/v1/auth/login", async (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        detail: { code: "2fa_required", challenge_token: "e2e-challenge" },
      }),
    }),
  );
  await page.route("**/api/v1/auth/2fa/login", async (route) => {
    session.signedIn = true;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ access_token: ACCESS_TOKEN, token_type: "bearer" }),
    });
  });
  // Seed-once — see mockApi.
  await page.addInitScript(
    ({ hasSession }) => {
      if (window.localStorage.getItem("tf_e2e_seeded") !== null) return;
      window.localStorage.setItem("tf_e2e_seeded", "1");
      window.localStorage.setItem("tf_has_session", hasSession ? "1" : "0");
    },
    { hasSession: signedIn },
  );
}
