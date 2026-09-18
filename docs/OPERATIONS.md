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

The `system.retention_cleanup` builtin job (global, daily 04:00 UTC, enabled
by default) enforces the day-based cutoffs. Audit rows are append-only and
kept forever unless the operator explicitly opts into deletion.

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
