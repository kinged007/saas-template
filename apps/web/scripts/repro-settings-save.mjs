/**
 * Repro harness for #237 — workspace settings "Save changes" crashing the dev
 * server into the error boundary with Radix Select's
 * "removeChild ... not a child of this node" NotFoundError.
 *
 *   BASE=http://localhost:5273 node scripts/repro-settings-save.mjs
 *   SAVES=20 BASE=... node scripts/repro-settings-save.mjs   # chase an intermittent
 *
 * Exits 0 when every save completed and the error boundary never fired, 1 when
 * it crashed, 2 when the harness itself could not drive the flow.
 *
 * On a hit it prints window.__lastErrorStack (set by ErrorBoundary): that stack,
 * not the message, is what identifies the crashing component. If it names an app
 * component above Presence/Portal the fault is app-side; if it names only
 * Presence/Portal it is @radix-ui/react-select and belongs upstream.
 */
import { chromium } from "playwright";

const BASE = process.env.BASE ?? `http://localhost:${process.env.WEB_PORT ?? 5173}`;
const SAVES = Number(process.env.SAVES ?? 3);
const TOKEN = "repro-token";
// Two workspaces, single_workspace false: a one-workspace identity renders the
// switcher as plain text, so the Radix Select portal never mounts at all.
const WORKSPACES = [
  { id: "11111111-1111-4111-8111-111111111111", name: "Acme Corp", slug: "acme-corp", role: "owner", permissions: ["*"] },
  { id: "22222222-2222-4222-8222-222222222222", name: "Globex", slug: "globex", role: "member", permissions: ["workspace:read"] },
];

const json = (body) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const identity = () => ({
  id: "00000000-0000-4000-8000-000000000000",
  email: "repro@example.com",
  display_name: "Repro User",
  workspaces: WORKSPACES,
  permissions: ["*"],
  single_workspace: false,
  is_superuser: false,
  profile: { first_name: "Repro", last_name: "User", display_name: "Repro User" },
});

// The app hit the error boundary, as opposed to the harness failing to drive it.
class Crash extends Error {}

const summary = async (where) => {
  const stack = await page.evaluate(() => window.__lastErrorStack ?? null);
  console.log(`\nurl:       ${page.url()}`);
  console.log(`stage:     ${where}`);
  console.log(`saves:     ${savesDone}/${SAVES}`);
  console.log(`__lastErrorStack: ${stack ?? "(unset)"}`);
  if (pageErrors.length) console.log(`pageerrors (${pageErrors.length}):\n${pageErrors.join("\n---\n")}`);
  return stack;
};

const fail = async (where) => {
  const stack = await summary(where);
  console.log(
    stack || pageErrors.some((e) => /removeChild|NotFoundError/.test(e))
      ? "\nFAIL: the error boundary caught a crash. File the stack above on #237."
      : "\nFAIL: the error boundary rendered, but it caught no removeChild error.",
  );
  process.exitCode = 1;
};

const browser = await chromium.launch({
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
const pageErrors = [];
const onPatch = [];
let savesDone = 0;

try {
  page.on("pageerror", (err) => pageErrors.push(String(err?.stack ?? err)));

  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname.replace(/^\/api\/v1/, "");
    if (path === "/auth/login" || path === "/auth/refresh") {
      return route.fulfill(json({ access_token: TOKEN, refresh_token: TOKEN }));
    }
    if (path === "/auth/me") return route.fulfill(json(identity()));
    if (path === "/auth/config") {
      return route.fulfill(json({ password_enabled: true, registration_enabled: true, providers: [] }));
    }
    const workspace = WORKSPACES.find((w) => path === `/workspaces/${w.id}`);
    if (workspace && req.method() === "PATCH") {
      Object.assign(workspace, req.postDataJSON() ?? {});
      onPatch.splice(0).forEach((resolve) => resolve());
      return route.fulfill(json(workspace));
    }
    // Everything else is a mounted list/panel (notifications, invitations,
    // search). These endpoints return a bare array, and the app iterates the
    // result unguarded in NotificationCenter — an object here would trip the
    // error boundary and mask the crash. A 401 would bounce to /login instead.
    return route.fulfill(json(req.method() === "GET" ? [] : {}));
  });

  const boundary = page.getByRole("heading", { name: "Something went wrong" });
  const switcher = page.locator('button[role="combobox"]').first();
  const save = page.getByRole("button", { name: "Save changes" }).first();

  await page.goto(`${BASE}/login`);
  await page.locator("#email").fill("repro@example.com");
  await page.locator("#password").fill("repro-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 30_000 });

  await page.goto(`${BASE}/settings/workspace/general`);
  // A crash can land anywhere in the flow, not only after the save click — the
  // settings page dies mid-render, so a missing Save button means a crash, not a
  // broken selector. Check before waiting on anything the crash would hide.
  await Promise.race([
    save.waitFor({ state: "visible", timeout: 30_000 }),
    boundary.waitFor({ timeout: 30_000 }).then(() => { throw new Crash("settings page"); }),
  ]);

  for (let i = 1; i <= SAVES; i++) {
    // The reported stack is SelectContent → Presence → Portal, and that content
    // only exists while the switcher dropdown is open. Open then dismiss it so
    // the portal mounts and unmounts around the save.
    await switcher.click();
    await page.getByRole("listbox").waitFor({ state: "visible", timeout: 10_000 });
    await page.keyboard.press("Escape");

    const patched = new Promise((resolve) => onPatch.push(resolve));
    await save.click();
    const outcome = await Promise.race([
      patched.then(() => "saved"),
      boundary.waitFor({ timeout: 15_000 }).then(() => "crashed"),
    ]);
    // refresh() refetches identity after the PATCH resolves, and the reported
    // crash lands in that re-render — let it settle before judging.
    await page.waitForTimeout(1000);
    if (outcome === "crashed" || (await boundary.isVisible())) {
      await fail(`save ${i}/${SAVES}`);
      break;
    }
    savesDone = i;
    console.log(`save ${i}/${SAVES}: ok`);
  }

  if (!process.exitCode) {
    const stack = await summary(`${SAVES} saves, no error boundary`);
    if (stack) {
      console.log("\nFAIL: __lastErrorStack is set but no boundary was seen — report the stack above on #237.");
      process.exitCode = 1;
    } else {
      console.log("\nPASS: no crash.");
    }
  }
} catch (err) {
  if (err instanceof Crash) {
    await fail(`${err.message} — before any save completed`);
  } else {
    console.error(`\nHARNESS ERROR (not a repro): ${err?.message ?? err}`);
    process.exitCode = 2;
  }
} finally {
  await browser.close();
}
