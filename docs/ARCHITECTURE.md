# SaaS Template — Architecture

## 1. Purpose

A production-oriented multi-tenant SaaS template: a FastAPI + SQLAlchemy
backend and a Refine.dev (React) frontend, covering the cross-cutting concerns
every SaaS product needs — auth, workspaces, RBAC, invitations, API keys,
notifications, an event bus, scheduled jobs and a WebSocket realtime layer —
as a coherent, tested reference implementation you can build a product on.

## 2. High-level topology

```
apps/api        FastAPI service: auth, workspaces, members, roles, invitations,
                API keys, notifications, scheduled jobs, outbound webhooks,
                WS realtime.
apps/web        Refine.dev SPA (React + Antd).
infra/          docker-compose, Dockerfiles, Helm chart, Terraform.
```

In development everything runs from the terminal (`uvicorn`, `vite dev`);
the API embeds PostgreSQL (pgserver) and NATS runs as a plain docker
container (`make nats-up`, `scripts/nats.sh`). In production the API scales
horizontally behind an ingress; NATS JetStream is the event backbone.

## 3. Domain model

```
User ──< WorkspaceMember >── Workspace (slug, name)
  │        (role_id, status)         │
  │                                  ├──< Role >── (permissions: string set)
  │                                  ├──< Invitation > (email, role_id, token, status)
  │                                  ├──< ApiKey > (name, key_prefix, permissions, revoked_at)
  │                                  ├──< WebhookSubscription > (url, event filter, active)
  │                                  │     └──< WebhookDelivery > (status, attempts, backoff)
  │                                  ├──< JobDefinition > (cron, params, enabled)
  │                                  │     └──< JobRun > (status, params snapshot, logs)
  │                                  └──< AuditLogEntry > (immutable, workspace-wide)
  ├──< RefreshToken >──< Notification > (user_id, type, payload, acknowledged_at)
  └──< UserProfile > (1:1 users, custom_data JSON, phone/timezone/locale etc.)
```

- **Workspace** — the tenancy boundary. Every workspace-scoped request carries
  `X-Workspace-ID`; all resources (members, roles, invitations, API keys, job
  definitions) hang off it.
- **Role / WorkspaceMember** — first-class roles hold a permission set
  (`<resource>:<action>` strings); members map users to a role in a workspace.
  Default system roles: `owner` (everything), `admin`, `editor`, `viewer`.
- **Invitation** — email-based invites with a token, status
  (`pending|accepted|declined|revoked|expired`) and expiry; accepting creates
  the membership (and the user if unregistered).
- **ApiKey** — per-user machine credentials with assignable permissions
  (capped by the minting principal's own permissions). Only the raw key is
  returned once at creation.
- **WebhookSubscription / WebhookDelivery** — workspace-scoped outbound
  webhooks: a subscription is a callback URL + event filter (empty = all);
  each matching domain event fans out into one delivery row per
  subscription, HMAC-signed, retried with backoff (1m→5m→30m→2h→12h, 6
  attempts) until success or `exhausted`. The signing secret lives in the
  `SecretStore`, returned once at creation. See `docs/WEBHOOKS.md`.
- **UserProfile** — 1:1 with `User` (`user_id` PK FK CASCADE), 9 common columns (`first_name`, `last_name`, `bio`, `phone_number`, `timezone`, `locale`, `date_of_birth`, `website_url`, `location`) + schemaless `custom_data JSON DEFAULT {}` (Merge Patch, 50 keys / 16 KiB). Lazily auto-created on `GET /me/profile` or `GET /auth/me` (ON CONFLICT), cascade-deleted with `User`. Cross-user read is workspace-bounded (404 if not co-member nor superuser) with redacted projection (`phone_number`, `date_of_birth`, `_private*` stripped). See `docs/providers/profile.md` for extension seam.
- **JobDefinition / JobRun** — DB-backed scheduled jobs (see §7).
- **Notification** — persisted per user/workspace, acknowledged via
  `PATCH /notifications/{id}`; pushed in realtime over WebSockets.
- **AuditLogEntry** — immutable audit trail for every user/system action
  (actor, IP, action, details), never updated; deleted only when the operator
  explicitly opts into `AUDIT_LOG_RETENTION_DAYS` (see docs/OPERATIONS.md).
  At most one entry per source event: the bus is at-least-once, so a
  redelivered event is not filed twice.
- **StoredSecret** — Fernet-encrypted values at rest (versioned key),
  namespaced per workspace, behind a `SecretStore` interface.

## 4. Multi-tenancy & RBAC

- JWT access token (15 min) carries `sub` (user id) + `sid` (session id, bound to the refresh-token row; see §5).
- Every workspace-scoped request sends `X-Workspace-ID: <uuid>`.
- Dependency `require_permission("member:read")` resolves the user's
  membership + role → permission set for that workspace and rejects with 403
  otherwise.
- Default roles seeded per workspace on creation:
  - `owner` — everything (`*`), cannot be removed
  - `admin` — manage members, roles, invitations, jobs
  - `editor` — read, manage API keys
  - `viewer` — read-only
- Role names are stripped on write (`POST /roles`, `PATCH /roles/{id}`) and
  compared exactly on read, so a row written before the strip existed can hold
  a padded name that no lookup (auto-join, name-based role lookups) matches.
  Remediation: rename the row with `PATCH /roles/{id}` — the payload name is
  stripped and the row's own id is excluded from the duplicate check, so
  resubmitting the row's padded name rewrites it stripped. A row named `Owner`
  (any case) is the owner role and refuses every edit with 403.
- Global (deployment-wide) administration — e.g. global jobs — is gated on
  the bootstrap superuser (`SUPERADMIN_EMAIL`), which does **not** bypass
  workspace-scoped checks.

## 5. Auth flows

| Flow | Mechanism |
|---|---|
| Password (browser) | `POST /auth/login` (`use_cookies: true`) → access JWT in JSON + refresh in `HttpOnly; SameSite=Lax` cookie, `Secure` per `cookie_secure_for()` (`REFRESH_COOKIE_SECURE` if set, else https request, else plain http outside `development`/`test`); `POST /auth/refresh` reads the cookie (rotating, hashed opaque token in DB); `POST /auth/logout` revokes + clears the cookie |
| Password (non-browser) | `POST /auth/login` → access + refresh in JSON; `POST /auth/refresh` takes `{"refresh_token"}` as before |
| 2FA / OAuth (browser) | `POST /auth/2fa/login` / `POST /auth/oauth/token` with `use_cookies: true` set the same cookie and omit the JSON refresh; the OAuth one-time code handoff carries only the access token for cookie callers |
| API keys | `Authorization: Bearer <key>`; permissions resolved per workspace (untouched by the cookie flow) |
| Identity | `GET /auth/me` → current user + workspaces + permissions + embedded `profile` (auto-created, same shape as `GET /me/profile`). `permissions` is principal-dependent: a session user gets the union of the roles it holds in the listed workspaces, an API key only its own grant — in the top-level field and in each `workspaces[]` entry alike (the nested entries still name the creator's membership role) |

SSO provider config is the `OAUTH_PROVIDERS` JSON list (shapes in `apps/api/.env.example`): OIDC providers come from discovery, non-OIDC (GitHub) lists explicit endpoint URLs; the optional `emails_url` key adds the private-email second lookup — pointed at `https://<host>/api/v3/user/emails` it covers GitHub Enterprise Server with no code.

API key quota: a key with a `usage_quota` is capped per calendar month (UTC).
`X-API-Key-Quota` / `X-API-Key-Remaining` report the month's limit and the uses
left in it; the counter resets on the first request of a new month and
`X-API-Key-Window-Reset` says when. `usage_count` stays the lifetime total.
The rollover, the quota test and the increment are one `UPDATE` and
`authenticate` takes the row lock, so concurrent requests on one key cannot
over-grant the budget.

Browser session storage model: the refresh token is never JS-readable (HttpOnly cookie, path `/api/v1/auth`); the 15-min access JWT lives in frontend memory only (nothing persists, so boot does one silent `POST /auth/refresh` — via the shared `ensureSession()` single-flight used by both `authProvider.check()` and the dataProvider 401 retry — to restore the session after reload, skipped entirely when the `tf_has_session` marker is absent). Cookie refresh/logout require the `X-Requested-With: XMLHttpRequest` header plus an allowlisted `Origin`/`Referer` (CSRF mitigation); non-browser JSON clients are unaffected. Future session endpoints (OAuth/2FA variants) must reuse `src/core/security/cookies.py` rather than reimplementing flags.

Session binding: every authenticated request costs one extra PK lookup
(`is_session_active`) to enforce immediate revocation; if that ever hurts,
use a short negative-cache on `(sid -> revoked)` with TTL, not a redesign.
Pre-deploy access tokens without `sid` are grandfathered (valid until
expiry, ≤15 min residual window).

Upgrading from a release without the quota window: migration `0019` seeds
`usage_window_count` from the lifetime `usage_count` and `usage_window_start`
from the start of the current month, so a key that had already exhausted its
old lifetime quota stays rejected until the next month boundary.
From that boundary on every key gets a fresh monthly budget, so a key that had
*not* exhausted its old lifetime cap is now renewable rather than one-shot.

## 6. Events & pub/sub

```
events/subjects.py     subject constants (workspaces.*, apikeys.*, audit.*, notifications.*, jobs.*)
events/bus.py          EventBus ABC: publish, subscribe, start, stop
events/inprocess.py    InProcessEventBus  (dev: asyncio in-process)
events/nats.py         NatsEventBus       (prod: NATS JetStream, streams + durable consumers)
workflows/*.py         subscribers orchestrated by a small WorkflowRegistry
```

- Domain events (e.g. `WorkspaceMemberInvited`, `NotificationCreated`) are
  published with a `CorrelationId`.
- The **notification workflow** subscribes to `notifications.*`, persists a
  `Notification` row for the target user, then pushes a realtime event over
  WebSockets. Notifications persist until the user acknowledges them
  (`PATCH /notifications/{id}` → `acknowledged_at`).
- **Job subjects** (`jobs.*`): `jobs.execute` (durable) — published when a
  scheduled job should run; consumed by the framework-level job scheduler.
- **Outbound webhooks**: every durable domain handler chains a fan-out
  (one pending `webhook_deliveries` row per matching subscription); a
  dispatcher loop CAS-claims due rows and POSTs them HMAC-signed, with
  backoff retry. See `docs/WEBHOOKS.md`.
- `NatsEventBus` uses JetStream:
  - One workqueue stream (`SAAS_TEMPLATE`) with subjects `workspaces.>`,
    `apikeys.>`, `audit.>`; durable consumers are **shared by name across
    replicas** — the server load-balances delivery (queue-group semantics
    without explicit bindings, which workqueue streams reject).
  - Handlers ack after success / nack on failure (redelivery, bounded by
    `max_deliver`). Publishes issued before the bus connects are buffered and
    flushed on start.
  - Durable subscriptions on transient subjects are rejected (a durable
    consumer there would never receive anything and would silently accumulate).
  - Deploy upgrades can strand stale consumers (workqueue streams allow one
    consumer per filter subject); the bus detects this and recovers by
    removing consumers bound to the subject before retrying.
  - **Realtime fan-out** (WS push) uses core NATS pub/sub instead: every API
    replica receives the event and pushes to its local WebSocket sessions, so
    the push reaches the user regardless of which replica holds their socket.
- Config flag: `EVENT_BUS_DRIVER=inprocess|nats`.

### Event contract (`src/events/subjects.py`)

Durable subjects (persisted, one workflow per subject, load-balanced):

| Subject | Workflow |
| --- | --- |
| `workspaces.member.invited` | persist a Notification row for the invitee |
| `workspaces.member.joined` | notify the inviter + other active members |
| `workspaces.member.role_changed` | notify the member whose role changed; an ownership transfer emits one event per user whose role actually changed (new owner promotion + previous owner demotion), against a single `workspace.ownership_transferred` audit record (see `docs/WEBHOOKS.md`) |
| `workspaces.member.removed` | notify the removed member |
| `workspaces.invitation.created` | email unregistered invitees; a failed send is audited (`invitation.email_failed`) |
| `workspaces.created` | provisioning/analytics hook (TODO) |
| `audit.entry.created` | persist an AuditLogEntry row |
| `apikeys.created` / `apikeys.revoked` | security/monitoring hook (TODO) |

Transient subject (core NATS, realtime fan-out, no persistence):

| Subject | Workflow |
| --- | --- |
| `notifications.created` | push to the user's WebSocket sessions |

Every user/automatic action publishes an audit event (`audit.entry.created`):
`user.register/login/token_refresh/logout`, `workspace.created/updated/deleted`,
`member.role_changed/removed/left`, `invitation.created/resent/accepted/declined/revoked/email_failed`, `user.session_revoked/sessions_revoked/refresh_token_reuse`,
`role.created`, `apikey.created/revoked`, `notification.acknowledged/
unacknowledged`, `notification.email_failed`, `job.run_*`. The audit workflow persists them (committed) to
`audit_log_entries`. `notification.email_failed` carries `details.reason` = `no_recipient | no_email | send_failed`.

## 7. Scheduled jobs

Framework-level scheduling with atomic execution, DB-backed definitions and
captured run history:

- **Registry** — services register specs (key, name, cron, params schema,
  scope, timeout, missed-run policy) with `job_registry`; rows are provisioned
  into `job_definitions` per scope (global specs get one row, workspace specs
  get one per workspace).
- **Definitions** — the DB row, not the code spec, is the source of truth:
  per-workspace schedule/params/enabled, `next_run_at` recomputed on
  enable/edit, `missed_policy` (`single` catch-up vs `ignore`).
- **Execution** — a scheduler publishes `jobs.execute`; the executor claims
  the run atomically, snapshots params (encrypted for password-type values),
  streams logging records and stdout/stderr into `job_logs`, and records
  status/duration/error on `job_runs`.
- **Built-ins** — `system.heartbeat` (global smoke test), a workspace demo
  job, and a global demo report; more jobs are registered in service code.

## 8. Refine compliance (API contract)

The backend follows `@refinedev/simple-rest` conventions so the frontend uses
zero-customization data access:

- `GET /{resource}?offset=0&limit=10&sort[]=f&order[]=asc&filter[k]=v` → list + `X-Total-Count`
- `GET /{resource}/{id}`
- `GET /{resource}?ids[]=a&ids[]=b` (getMany)
- `POST /{resource}` → 201 + entity
- `PATCH /{resource}/{id}` → 200 + entity
- `DELETE /{resource}/{id}` → 204

A shared `crud` helper turns Refine params into safe SQLAlchemy queries
(whitelisted sort/filter fields per resource). Every sorted list ends on the
row's primary key, in the direction of the last sort key, so the order is total
and `offset`/`limit` paging cannot drop or repeat a row when the sorted columns
tie. Ties resolve by `id`, not by insertion order — the ids are UUIDs.

## 9. Security

- bcrypt password hashing, Fernet-encrypted secrets (versioned keys)
- CORS allowlist from env (`allow_credentials` on); refresh-token rotation + revocation
- Browser refresh tokens in `HttpOnly; SameSite=Lax` cookies (JS cannot exfiltrate them); `Secure` is resolved per request by `cookie_secure_for()` — `REFRESH_COOKIE_SECURE` if set, else https, else plain http only when `ENVIRONMENT` is neither `development` nor `test`; CSRF covered by SameSite + `Origin`/`Referer` allowlist check + required `X-Requested-With` custom header on cookie-authenticated refresh/logout
- HttpOnly narrows theft to the live session — injected JS can still ride the session while the page is open, so CSP and output escaping remain the real XSS defense
- Permission checks server-side on every workspace-scoped route
- No secrets in responses; API-key raw values returned once at creation

## 10. Deployment

- **Dev**: docker-compose → postgres + nats; run `make api` / `make web` from terminal
- **Container**: `infra/docker/` (multi-stage Dockerfiles)
- **Kubernetes**: `infra/helm/saas-template` (api, web, postgres optional, nats optional, ingress, secrets)
- **Cloud**: `infra/terraform/` example — AWS EKS + RDS + NATS on EKS via Helm
  (same chart used for GCP GKE / Azure AKS)
- All services 12-factor: config via env, structured logs, `/healthz` + `/readyz`
