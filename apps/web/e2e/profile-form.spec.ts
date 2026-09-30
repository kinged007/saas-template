import { expect, type Page } from "playwright/test";

import { test } from "./fixtures";

/**
 * The general profile form must render the saved profile on a hard reload
 * (#461). Every backend call is mocked, so the spec runs without an API:
 * `/auth/me` embeds a profile, `GET /me/profile` returns the same resource.
 */

const PROFILE = {
  id: "user-1",
  user_id: "user-1",
  first_name: "Reviewer",
  last_name: "U",
  bio: "hello",
  phone_number: null,
  timezone: "Europe/Berlin",
  locale: "en",
  date_of_birth: null,
  website_url: null,
  location: null,
  custom_data: {},
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

/** The shape `ProfileService.get_or_create` failure leaves in `/auth/me`. */
const NULL_PROFILE = {
  id: "user-1",
  user_id: "user-1",
  first_name: null,
  last_name: null,
  bio: null,
  phone_number: null,
  timezone: null,
  locale: null,
  date_of_birth: null,
  website_url: null,
  location: null,
  custom_data: {},
  created_at: null,
  updated_at: null,
};

const IDENTITY = {
  id: "user-1",
  email: "e2e@example.com",
  display_name: "Reviewer U",
  is_superuser: true,
  permissions: ["*"],
  workspaces: [{ id: "ws-1", name: "Acme Corp", role: "owner" }],
  single_workspace: true,
};

const ACCESS_TOKEN = [
  btoa(JSON.stringify({ alg: "HS256", typ: "JWT" })),
  btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600, sub: "user-1" })),
  "sig",
].join(".");

/** Holds `GET /me/profile` until `release` is called. */
function hold() {
  let release!: () => void;
  const settled = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { settled, release };
}

/**
 * @param profile  what `/auth/me` embeds: omitted, `null`-fielded or full
 * @param fetched  what `GET /me/profile` answers once `gate` settles
 * @param gate     awaited inside the `GET /me/profile` handler, so the test
 *                 decides when that request lands
 */
async function mockApi(
  page: Page,
  {
    profile,
    fetched = PROFILE,
    gate,
  }: {
    profile?: Record<string, unknown>;
    fetched?: Record<string, unknown> | null;
    gate?: Promise<void>;
  },
) {
  await page.route("**/api/v1/**", async (route) => {
    const reply = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    const { pathname } = new URL(route.request().url());
    if (pathname.endsWith("/auth/refresh")) {
      return reply(200, { access_token: ACCESS_TOKEN, token_type: "bearer" });
    }
    if (pathname.endsWith("/auth/me")) {
      return reply(200, profile ? { ...IDENTITY, profile } : IDENTITY);
    }
    if (pathname.endsWith("/me/profile")) {
      if (gate) await gate;
      if (!fetched) return reply(500, { detail: "boom" });
      return reply(200, fetched);
    }
    if (pathname.endsWith("/auth/config")) {
      return reply(200, { registration_enabled: true, password_enabled: true, oauth_enabled: false, providers: [] });
    }
    if (pathname.endsWith("/auth/logout")) return route.fulfill({ status: 204, body: "" });
    return reply(200, []);
  });
  await page.addInitScript(() => window.localStorage.setItem("tf_has_session", "1"));
}

const openGeneral = async (page: Page) => {
  await page.goto("/settings/profile/general");
  await expect(page.getByLabel("First name")).toBeVisible();
};

test.describe("profile form boot", () => {
  test("fills the form from the profile fetch when /auth/me embeds no profile", async ({ page }) => {
    await mockApi(page, {});
    await openGeneral(page);
    await expect(page.getByLabel("First name")).toHaveValue("Reviewer");
  });

  test("ignores an all-null profile embedded in /auth/me", async ({ page }) => {
    await mockApi(page, { profile: NULL_PROFILE });
    await openGeneral(page);
    await expect(page.getByLabel("First name")).toHaveValue("Reviewer");
  });

  test("fills the form from the /auth/me embed before the fetch resolves", async ({ page }) => {
    const fetch = hold();
    await mockApi(page, { profile: PROFILE, gate: fetch.settled });
    await openGeneral(page);
    // The fetch is still held, so only the embed can have filled the input.
    await expect(page.getByLabel("First name")).toHaveValue("Reviewer");
    fetch.release();
  });

  test("keeps typed input when the profile fetch resolves afterwards", async ({ page }) => {
    const fetch = hold();
    // A blank embed paints an empty form and the fetch then answers with
    // different content, so RHF's reset really runs instead of being skipped by
    // its deepEqual guard.
    await mockApi(page, { profile: NULL_PROFILE, gate: fetch.settled });
    await openGeneral(page);
    await page.getByLabel("Bio").fill("TYPED-BIO");
    fetch.release();
    await expect(page.getByLabel("First name")).toHaveValue("Reviewer");
    await expect(page.getByLabel("Bio")).toHaveValue("TYPED-BIO");
  });

  test("survives a failing profile fetch", async ({ page }) => {
    await mockApi(page, { profile: PROFILE, fetched: null });
    await openGeneral(page);
    await expect(page.getByLabel("First name")).toHaveValue("Reviewer");
  });
});
