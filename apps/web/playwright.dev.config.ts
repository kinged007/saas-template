import { defineConfig } from "playwright/test";

// Real backend, no mocks: the signed-in route has to be reachable in the dev
// stack the way a browser reaches it. baseURL is the 127.0.0.1 alias on
// purpose — `make dev` allowlists the web origin on both loopback names, and
// a stack that only works on `localhost` is the regression this run guards.
// Ports 8038/5318 keep it clear of a running `make dev` (8027/5289).
const API_PORT = Number(process.env.API_PORT ?? 8038);
const WEB_PORT = Number(process.env.WEB_PORT ?? 5318);
const baseURL = `http://127.0.0.1:${WEB_PORT}`;
// A dedicated file DB so this run never migrates or seeds the dev.db that a
// developer's own `make dev` holds open.
const DB = "sqlite+aiosqlite:///./e2e-dev.db";

export default defineConfig({
  // dev-session.spec.ts drives the real stack; routing.spec.ts mocks the API
  // and belongs to playwright.config.ts.
  testDir: "./e2e",
  testMatch: "**/dev-session.spec.ts",
  forbidOnly: !!process.env.CI,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  use: { baseURL },
  // Manual only, not in CI: it migrates, seeds and boots the whole dev stack.
  webServer: {
    command: [
      `export USE_SQLITE=1 API_PORT=${API_PORT} WEB_PORT=${WEB_PORT} DATABASE_URL=${DB}`,
      "cd ../api",
      "uv run alembic upgrade head",
      "uv run python -m src.seed",
      "cd ../..",
      "exec python3 scripts/dev.py",
    ].join(" && "),
    url: baseURL,
    reuseExistingServer: false,
    timeout: 180_000,
    // dev.py re-arms SIGTERM and tears down its own uvicorn/vite process
    // groups; without this Playwright SIGKILLs it and orphans both servers.
    gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
  },
});
