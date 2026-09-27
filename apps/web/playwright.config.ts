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
  use: { baseURL },
  webServer: {
    command: `npm run dev -- --port ${PORT} --strictPort`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
