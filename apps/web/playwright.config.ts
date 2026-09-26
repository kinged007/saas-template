import { defineConfig } from "playwright/test";

// Port 5317 keeps the e2e dev server off the default 5173, so a running
// `make dev` is not disturbed. The specs mock every /api/v1 call, so no
// backend (and no DATABASE_URL) is needed.
const PORT = 5317;
const baseURL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL },
  webServer: {
    command: `npm run dev -- --port ${PORT} --strictPort`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
