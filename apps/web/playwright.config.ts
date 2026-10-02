import { defineConfig } from "playwright/test";

import { e2eServer } from "./e2e/server.ts";

// Port 5317 keeps the e2e dev server off the default 5173, so a running
// `make dev` is not disturbed. The specs mock every /api/v1 call, so no
// backend (and no DATABASE_URL) is needed. E2E_PORT claims a different port when
// another run already holds 5317; E2E_REUSE_SERVER=1 attaches to it instead.
const { port, baseURL, reuse } = e2eServer();

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: !!process.env.CI,
  // The first spec pays the cold cost of vite transforming the app module
  // graph, which exceeds the 30s default on a GitHub runner. Both of these are
  // per-test options, so they sit at the top level rather than under `use`.
  timeout: 90_000,
  expect: { timeout: 10_000 },
  // One shared vite dev server serves every worker, and Playwright otherwise
  // defaults to half of all cores. The cap keeps that server alive on a large
  // machine; CLI --workers still overrides it.
  workers: 4,
  use: { baseURL },
  webServer: {
    command: `npm run dev -- --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: reuse,
    timeout: 120_000,
  },
});