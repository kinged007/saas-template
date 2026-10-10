# Operations: observability, retention, backup/restore

## Request tracing

Every HTTP response carries `X-Request-ID`. Send your own (`curl -H
"X-Request-ID: abc123" …`) to correlate client-side with server-side, or let
the API mint one (16 hex chars). The id is echoed back on the response and
anchors one INFO log line per request:

```
rid=abc123 GET /api/v1/workspaces/{id} -> 200 12ms
```

Path labels use route templates, never raw ids. `GET /healthz` and `GET
/readyz` stay unauthenticated for load-balancer probes.

## Client IP attribution

The API never parses `X-Forwarded-For` itself. It records `scope["client"]`,
which uvicorn's `ProxyHeadersMiddleware` overwrites from `X-Forwarded-For` —
but only when uvicorn runs with `--proxy-headers` and the connecting peer
matches `--forwarded-allow-ips`. Everything recorded from that address (session
rows, audit log entries, webhook deliveries) is correct as long as that flag
names your proxy. `infra/docker/docker-compose.prod.yml` pins the compose
network to `172.30.0.0/24` and defaults `FORWARDED_ALLOW_IPS` to that subnet —
the api service publishes no ports, so nginx is its only peer — and
`infra/docker/.env` overrides it.

Keep the list narrow. Under `'*'`, uvicorn takes the leftmost `X-Forwarded-For`
entry verbatim, so any peer that can reach the API port picks the address
recorded against it. Set the flag to your proxy's IP, CIDR, or a
comma-separated list. Running the image outside compose already supplies both
proxy flags: the CMD wires `--forwarded-allow-ips` to `FORWARDED_ALLOW_IPS`
with a loopback-only default, quoted so a value with spaces stays one argv.
Set `FORWARDED_ALLOW_IPS` to your proxy's address; until you do, no header is
honoured and every address is the proxy's. The CMD does not run migrations
(only the compose `command:` does), so apply `alembic upgrade head` yourself
before starting the image outside compose.

Behind an external load balancer or CDN, add its address to
`FORWARDED_ALLOW_IPS`. nginx appends to `X-Forwarded-For`, so an unlisted LB
makes uvicorn stop at the LB entry: every recorded client IP becomes the LB's,
and every IP-keyed limiter collapses into one bucket shared by all users —
the OAuth limiter (`oauth:{ip}:{provider}` at
`apps/api/src/api/routes/oauth.py`) and, worse, the register limiter
(`apps/api/src/api/routes/auth.py`), whose key is the client IP alone: all
signups site-wide share one register window, so one abuser behind that
shared address blocks every new user from registering until it drains.

Only `X-Forwarded-For` is honoured. `X-Real-IP` and `CF-Connecting-IP` are read
by neither uvicorn nor this code, so a proxy configured to send only
`X-Real-IP` records the proxy's address.

## Client scheme attribution

`cookie_secure_for()` (`apps/api/src/core/security/cookies.py`) sets `Secure`
on the refresh cookie only for HTTPS sessions, reading the scheme from
`request.url.scheme` or the leftmost `X-Forwarded-Proto`. A TLS-terminating
load balancer ends HTTPS and forwards plain HTTP to nginx, so nginx's `$scheme`
is always `http`; without a fix the API never sees `https` and skips `Secure`.

`infra/docker/nginx.conf` fixes this on the `/api/` and `/api/v1/ws` locations.
It proves the requesting peer is a proxy this deployment trusts — a
`geo $trusted_proxy` set of private and loopback ranges, the `172.30.0.0/24`
compose subnet included, no trust-all default — and only for such a peer
forwards that peer's `X-Forwarded-Proto` (leftmost entry of a chain, `http` or
`https`, case-insensitive) to the API. Any other peer, including a client that
forges the header straight at nginx, falls back to the local `$scheme`, so a
spoofed `https` cannot upgrade a plain-HTTP request.

Narrow it before going public. nginx has no env-configurable `geo`, so edit the
ranges in `infra/docker/nginx.conf` to the load balancer's exact address; the
shipped ranges cover an LB inside a private network, not the public internet.
The one conf is baked into the web image (Dockerfile.web), so every deployment
running that image shares this edit.

## Metrics

`GET /metrics` exposes Prometheus text exposition (no auth, same as
`/healthz` — point your scraper at it):

| Counter | Labels | Meaning |
|---|---|---|
| `http_requests_total` | `method`, `path` (route template), `status` | requests served |
| `job_runs_total` | `key`, `status` | finished job runs by outcome |
| `webhook_deliveries_total` | `outcome` | delivery attempts by outcome |

Counters are process-level and reset on restart (Prometheus treats this as a
counter reset). Multi-replica deployments should scrape every replica or
federate behind a gateway.

## Retention

Settings (env vars, days; `0` disables that cutoff):

| Setting | Default | Deletes |
|---|---|---|
| `JOBS_RUN_RETENTION` | 1000 | newest-N job runs per definition (scheduler housekeeping, hourly) |
| `JOBS_LOG_RETENTION_DAYS` | 90 | job runs + logs older than cutoff |
| `NOTIFICATIONS_RETENTION_DAYS` | 90 | acknowledged notifications older than cutoff (unacknowledged are kept) |
| `AUDIT_LOG_RETENTION_DAYS` | 0 (forever) | audit entries older than cutoff, only when non-zero |
| `API_KEY_RETENTION_DAYS` | 30 | API keys revoked before the cutoff, in every workspace (`apikeys.cleanup`; 0 keeps them) |

The `system.retention_cleanup` builtin job (global, daily 04:00 UTC, enabled
by default) enforces the day-based cutoffs. Audit rows are append-only and
kept forever unless the operator explicitly opts into deletion by setting a
non-zero `AUDIT_LOG_RETENTION_DAYS` — this breaks the ARCHITECTURE.md
"never updated or deleted" guarantee, so only enable it where a data-
retention policy requires it.

The `apikeys.cleanup` builtin job (global, daily 05:00 UTC, enabled by
default) enforces `API_KEY_RETENTION_DAYS`. It revokes keys that are not
already revoked and whose `expires_at` has passed — those keys already fail
authentication, so revoking them records state that stopped working — then
hard-deletes every key whose `revoked_at` is past the cutoff. That
hard-delete has no workspace filter, so one run removes rows in every
workspace of every tenant. The clock runs from `revoked_at`, not from
`expires_at`: a key revoked by a user starts the window then, and a key
expired by the job starts when the job revoked it, so nothing is deleted
on the day it expires. Each revocation publishes an `apikeys.revoked` event
and an `apikey.revoked` audit entry with `reason: "expired"` and no actor.

## Backup / restore

- **Managed Postgres** (`DATABASE_URL` set): use the provider's automated
  backups (e.g. RDS snapshots with point-in-time recovery). For ad-hoc dumps:
  `pg_dump "$DATABASE_URL" > backup.sql`, restore with `psql "$DATABASE_URL"
  < backup.sql`.
- **Embedded Postgres** (default dev, data dir from `src/db/embedded.py`):
  stop the API first (the server owns the data dir), then either `pg_dump -h
  <socket> backup.sql` or copy the whole data directory. Restore by
  replaying the dump or putting the directory back before restart.
- **SQLite dev DB** (`USE_SQLITE=1`, `apps/api/dev.db`): stop the API, then
  `cp dev.db dev.db.bak`. Restore by copying back.
- Secrets at rest are Fernet-encrypted: keep `FERNET_KEYS` (and the
  `SECRET_ENCRYPT_VERSION` pointer) with the backup or restored rows cannot
  be decrypted.
