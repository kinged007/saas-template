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

## Response headers

Every `/api/*` response carries `X-API-Version`. A request authenticated with
an API key that has a `usage_quota` set additionally carries these three; an
unlimited key carries none of them:

| Header | Meaning |
|---|---|
| `X-API-Key-Quota` | The key's monthly cap |
| `X-API-Key-Remaining` | Uses left in the current calendar month (UTC) |
| `X-API-Key-Window-Reset` | IMF-fixdate of the next month boundary, when the counter resets |

All three ride on the `403 api key quota exceeded` rejection as well, so a
client that has run out can still read its budget and when it recovers.
`Remaining` counts the request being answered, so it reaches `0` on the last
accepted call and the next call is rejected.

### Changed meanings

`usage_quota` and `X-API-Key-Remaining` were lifetime-scoped and are now per
calendar month (UTC). The names are unchanged and both stay under `/api/v1`,
so this is the one departure from the additive-only rule above. It is
announced in the release notes for the release that carries it (issue #69),
and no version bump was taken because the per-month cap is that issue's
intent and the lifetime reading was the defect — not a stable contract that a
client could have relied on. A client that tracked "remaining for the life of
this key" must read the calendar month instead: the number climbs back on the
1st.

## Why prefix strategy

URL prefixes are visible in logs, trivially routable at the ingress, and need
no content negotiation. No header/query-param versioning.
