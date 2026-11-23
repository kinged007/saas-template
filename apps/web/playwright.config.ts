import { defineConfig } from "playwright/test";

// Port 5317 keeps the e2e dev server off the default 5173, so a running
// `make dev` is not disturbed. The specs mock every /api/v1 call, so no
// backend (and no DATABASE_URL) is needed.
const PORT = 5317;
const baseURL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  // dev-session.spec.ts needs the real stack — playwright.dev.config.ts.
  testIgnore: "**/dev-session.spec.ts",
  forbidOnly: !!process.env.CI,
  // The first spec pays the cold cost of vite transforming the app module
  // graph, which exceeds the 30s default on a GitHub runner. Both of these are
  // per-test options, so they sit at the top level rather than under `use`;
  // the expect budget is raised too, because a cold page load is slow for
  // assertions on that page as well.
  timeout: 90_000,
  expect: { timeout: 30_000 },
  // The two directories ci.yml uploads on a red run. Declared rather than left
  // at their defaults so the paths the workflow names live in this file too.
  outputDir: "test-results",
  // Without a reporter a CI run is a dot log and an exit code, so a red job
  // said nothing about which spec failed or why. The HTML report is what gets
  // uploaded; `open: "never"` because a failing run must not hang on a server.
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]]
    : "list",
  use: {
    baseURL,
    // Chromium's back/forward cache restores a document on goBack() without
    // re-running its scripts, so a spec that navigates back to prove a remount
    // observes a restored DOM and no network. That is what made
    // oauth-callback's latch spec red on CI while passing locally. Off for
    // every spec: a test must not depend on which browser cache served it.
    launchOptions: { args: ["--disable-features=BackForwardCache"] },
    // A retained trace is the only record of the DOM, network and console of a
    // failure that is gone by the time anyone reads the log. It carries the
    // full network log, so it is safe only while every spec mocks /api/v1;
    // point one at a real backend and the artifact holds credentials. Only in
    // CI: the trace is recorded on every test and discarded on a pass, so a
    // local run pays that cost for an artifact nobody uploads.
    trace: process.env.CI ? "retain-on-failure" : "off",
    // "on-first-retry" would never fire with retries: 0, so every failure
    // gets one. ponytail: no retries, a flake is red rather than green on a
    // second run; add `retries` when a flake actually shows up.
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `npm run dev -- --port ${PORT} --strictPort`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
