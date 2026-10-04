# API Versioning

All API routes live under `/api/v1`. The `v1` prefix is part of the contract:
clients must send it, and the server stamps every `/api/*` response with
`X-API-Version: v1` (also exposed via CORS). `GET /` reports the same version
as `api_version`.

## Rules

- **Additive changes only within a version**: new routes and new optional
  request/response fields are fine; renaming, removing, or changing the
  meaning of an existing field is not — that needs a new version.
- **New version**: mount a second prefix (`/api/v2`) alongside v1 in
  `apps/api/src/main.py` and bump `API_VERSION`. Keep v1 serving until every
  documented consumer has migrated.
- **Deprecation**: announce in release notes first; serve the old version for
  at least one minor release with a `Sunset` response header before removal.
- **Status-code corrections are not breaking changes**: a route that returned
  the wrong status for a documented caller keeps its route and payload, so no
  new prefix is required — but the correction is recorded here and in the
  release notes.

## Recorded corrections

- `GET /api/v1/jobs/{id}`, `PATCH /api/v1/jobs/{id}`,
  `POST /api/v1/jobs/{id}/execute` and `GET /api/v1/jobs/{id}/runs` return
  `403 "you are not a member of this workspace"` — not `404 "job not found"` —
  for an authenticated user who is not a member of the definition's workspace.
  This matches the run routes and every other workspace-owned resource. An
  API key scoped to another workspace still gets `404`, so key callers learn
  nothing about definitions outside their scope.
- `GET /api/v1/jobs/runs/{id}` and `GET /api/v1/jobs/runs/{id}/logs` answer
  an API-key caller with `403 "deployment administration is not available to
  API keys"` for every run it may not read: a global run, a run outside the
  key's workspace, and an id matching no run — one answer for all three, so no
  pair of them tells the key which state produced it. A session caller still
  gets `404 "run not found"` for an id matching no run.

## Why prefix strategy

URL prefixes are visible in logs, trivially routable at the ingress, and need
no content negotiation. No header/query-param versioning.
