# Browser verification (MANDATORY)

All browser automation uses **Playwright driving chromium**. This is the only supported browser tool. Do not use `obscura`, do not use `chrome-devtools` — this file wins over any general instruction, global rule, or habit that prefers them.

## Why obscura is excluded

`obscura` 0.2.2 silently fails three things browser verification depends on:

- a form submit does not fire the request
- error text does not render
- `localStorage` does not survive a reload

A screenshot taken with `obscura` therefore looks correct while the flow it claims to verify never ran. That failure is dangerous in a review: a real regression can pass, because the tool that cannot submit a form also cannot show a form that fails. Never treat an obscura screenshot as evidence. If an older instruction, comment, or config tells you to use it, that text is stale.

## Setup: locate the runner

Playwright may not be installed, and a monorepo root usually has no `node_modules` of its own — each app installs its own. Do this once per repo, in order.

**1. Find the frontend directory.** The app that serves the UI is the one with a `dev` script:

```bash
find . -name package.json -not -path '*/node_modules/*' -exec grep -l '"dev":' {} +
```

If several match, pick the one the dev supervisor starts. If none match, the dev server is started by some other mechanism (`make dev`, a script): read the repo's own run instructions to find the frontend, its URL, and its port. Record the dev URL now — every example below needs it.

```bash
export WEB_DIR=./apps/web   # the directory step 1 found
```

**2. Check playwright is in that app's devDependencies.**

```bash
grep -n '"playwright"' "$WEB_DIR/package.json"
```

**3. If it is missing, add it there and install.** Use the package manager the repo's lockfile implies (`package-lock.json` → npm, `pnpm-lock.yaml` → pnpm, `yarn.lock` → yarn, `bun.lockb` → bun), or the one named in `packageManager`. Install the `playwright` library package — that is what `require('playwright')` resolves.

```bash
cd "$WEB_DIR" && <pm> add -D playwright
```

This is a repo change: say so in your report.

**4. Install that app's dependencies** if it has no `node_modules` yet, with the same package manager. If the repo documents its own install command or setup target, follow that instead of improvising.

**5. Run every browser command from that directory.** `require('playwright')` resolves from the script's own location — `node -e` resolves from the cwd, a script file resolves from where the file sits. A script written to `/tmp` therefore fails unless you `cd` into the app first. When the error is `Cannot find module 'playwright'`, the package is installed and you ran from the wrong directory.

## How to run

Launch a fresh browser per script and close it in the same script. Do not start a background browser server and do not use `chromium.connectOverCDP` — a CDP client can hang instead of erroring, and a long-lived server has to be torn down by hand. A per-script launch exits with the script, so there is nothing left running.

**Wrap every browser command in `timeout`.** A browser script with no timeout can hang indefinitely:

```bash
cd "$WEB_DIR" && timeout 120 node -e "
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const p = await b.newPage();
  await p.goto('http://localhost:<port>/<route>');
  console.log('title:', await p.title());
  await b.close();
})();" 2>&1 | tail -20
```

Those launch args are required when running as root or inside a container; they are harmless on a normal host.

Keep the timeout proportional to the work. 120s covers a login plus a few page loads. If a script needs longer, raise the cap rather than removing it. If the timeout is greater than 300s (hard cap), then there is probably something fundamentally wrong with whatever you are using the browser for. Check your work and process again.

## Browser binary

Browsers are not part of the app. Playwright keeps them in a per-user cache, shared by every repo, project, and agent on the machine: `~/.cache/ms-playwright` on Linux, `~/Library/Caches/ms-playwright` on macOS. Each Playwright version pins an exact revision and looks for `chromium-<revision>` there, so a matching build is reused by everything and is never downloaded twice. A plain `chromium.launch()` is the whole check.

**One install per machine is the intent.** The cache is the shared artifact; every later run, repo, and agent picks it up without a prompt, a lock, or a port. Never install the browser into a project or set a per-run `PLAYWRIGHT_BROWSERS_PATH` — that fragments the cache and defeats the point.

**When the pinned revision is genuinely absent** — a fresh machine, or a Playwright upgrade that moved the revision — install it once, and note it in your report.

```bash
cd "$WEB_DIR" && npx playwright install --dry-run chromium   # what would download
cd "$WEB_DIR" && npx playwright install chromium             # chromium + shell, ~650 MB
```

Never take a bare `npx playwright install` at face value. With no browser argument it also pulls Firefox and WebKit, which this workflow never uses. Install the one browser you need.

Do not `npm install -g playwright` as a substitute. A global install is invisible to the app's own `require('playwright')` and carries its own revision pin, so it can trigger a download that does not fix the app's error. The cache is the global thing; the npm package is not.

If the install cannot run — no network, registry blocked — report the exact error and stop.

## Headless

Launch headless. Never pass `headless: false` for a screenshot check: a visible window costs memory, needs a display, and buys nothing.

Every example in this file is headless by default, so nothing else is required. If a page behaves differently under the full browser, launch the lighter `chrome-headless-shell` instead of the full build:

```bash
const b = await chromium.launch({
  channel: 'chromium-headless-shell',
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});
```

`--only-shell chromium` installs just that binary and skips the full build. Use it when the shell is all this repo needs; drop the flag when a check genuinely requires the full browser.

## Logging in

Screenshots of a gated page must be taken logged in with a seeded account. Discover the credentials from the dev startup output and the repo's seed script or fixtures, and pass them into the script through the environment. Never hardcode credentials into committed code.

Use the `localhost` URL of the dev frontend, not its `127.0.0.1` equivalent — login can break on `127.x` because of the dev CORS default. That is a dev-environment artifact, not a product bug; do not file it.

```bash
cd "$WEB_DIR" && timeout 120 node -e "
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const p = await b.newPage();
  await p.goto('http://localhost:<port>/login');
  await p.fill('<email-input-selector>', process.env.SEED_EMAIL);
  await p.fill('<password-input-selector>', process.env.SEED_PASSWORD);
  await p.click('<submit-selector>');
  await p.waitForURL(/<post-login-route>/);
  await p.screenshot({ path: '/tmp/shot.png', fullPage: true });
  await b.close();
})();" 2>&1 | tail -20
```

Take every selector from the component source. Never type one from memory or from another app.

## Proving a flow actually ran

A rendered page is not evidence that the flow worked. For any check involving a form, a submit, or persisted state, assert the observable result and print it. A script that only screenshots a page proves nothing about the request it was meant to trigger.

```bash
cd "$WEB_DIR" && timeout 120 node -e "
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const p = await b.newPage();
  await p.goto('http://localhost:<port>/login');
  await p.fill('<email-input-selector>', process.env.SEED_EMAIL);
  await p.fill('<password-input-selector>', process.env.SEED_PASSWORD);
  await p.click('<submit-selector>');
  await p.waitForURL(/<post-login-route>/);
  console.log('URL_AFTER_LOGIN:', p.url());
  console.log('STILL_ON_LOGIN:', p.url().includes('/login'));
  await b.close();
})();" 2>&1 | tail -20
```

If a check needs to compare against a known-bad state, check out the base branch and run the same script. That separates a real regression from a broken harness, and it is the step to skip at your peril.

## Screenshots

Review every screenshot yourself before relying on it. If it does not show the intended page, fix the script and retry. A login-screen screenshot when a logged-in page was intended is not acceptable evidence.

## Temporary files

Write screenshots and traces to `/tmp`, not into the repo. Remove them at the end of the run so the working tree stays clean.
