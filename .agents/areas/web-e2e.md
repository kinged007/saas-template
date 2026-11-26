# web-e2e

Paths: `apps/web/e2e/**`, `apps/web/playwright.config.ts`, `apps/web/playwright.dev.config.ts`.

Purpose: Playwright specs for the SPA. Specs mock every `/api/v1` call, so no API process is needed.

Entry points:
- `e2e/mock-api.ts`: mock API handlers and the default `IDENTITY`.
- `e2e/fixtures.ts`: shared fixtures.
- `playwright.config.ts`: starts `npm run dev` on port 5317 so a running `make dev` is not disturbed.
- `playwright.dev.config.ts`: config for `npm run test:e2e:dev`.

Conventions:
- One `<topic>.spec.ts` per behavior; add routes to `mock-api.ts` instead of per-spec stubs when several specs need them.
- `e2e/mock-api.typecheck.ts` type-checks the mock against `src/types.ts`.

Pitfalls:
- A change to API response shapes in `apps/web/src/types.ts` needs a matching change in `mock-api.ts`.
- CI runs e2e only on pushes to `main` and manual dispatch (`.github/workflows/e2e.yml`), not on pull requests.

Checks:
- `make web-test-e2e` (`cd apps/web && npx playwright install chromium && npm run test:e2e`)
