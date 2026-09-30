import { defineConfig } from "playwright/test";

// Port 5317 keeps the e2e dev server off the default 5173, so a running
// `make dev` is not disturbed. The specs mock every /api/v1 call, so no
// backend (and no DATABASE_URL) is needed.
const PORT = 5317;
const baseURL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: !!process.env.CI,
  // The first spec pays the cold cost of vite transforming the app module
  // graph, which exceeds the 30s default on a GitHub runner. Both of these are
  // per-test options, so they sit at the top level rather than under `use`.
  timeout: 90_000,
  expect: { timeout: 10_000 },
  // Without a reporter a CI run is a dot log and an exit code, so a red job
  // said nothing about which spec failed or why. The HTML report is what gets
  // uploaded; `open: "never"` because a failing run must not hang on a server.
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL,
    // A retained trace is the only record of the DOM, network and console of a
    // failure that is gone by the time anyone reads the log.
    trace: "retain-on-failure",
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
