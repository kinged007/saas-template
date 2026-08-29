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
                API keys, notifications, scheduled jobs, WS realtime.
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
- **UserProfile** — 1:1 with `User` (`user_id` PK FK CASCADE), 9 common columns (`first_name`, `last_name`, `bio`, `phone_number`, `timezone`, `locale`, `date_of_birth`, `website_url`, `location`) + schemaless `custom_data JSON DEFAULT {}` (Merge Patch, 50 keys / 16 KiB). Lazily auto-created on `GET /me/profile` or `GET /auth/me` (ON CONFLICT), cascade-deleted with `User`. Cross-user read is workspace-bounded (404 if not co-member nor superuser) with redacted projection (`phone_number`, `date_of_birth`, `_private*` stripped). See `docs/providers/profile.md` for extension seam.
- **JobDefinition / JobRun** — DB-backed scheduled jobs (see §7).
- **Notification** — persisted per user/workspace, acknowledged via
  `PATCH /notifications/{id}`; pushed in realtime over WebSockets.
- **AuditLogEntry** — immutable audit trail for every user/system action
  (actor, IP, action, details), never updated or deleted.
- **StoredSecret** — Fernet-encrypted values at rest (versioned key),
  namespaced per workspace, behind a `SecretStore` interface.

## 4. Multi-tenancy & RBAC

- JWT access token (15 min) carries `sub` (user id) only.
- Every workspace-scoped request sends `X-Workspace-ID: <uuid>`.
- Dependency `require_permission("member:read")` resolves the user's
  membership + role → permission set for that workspace and rejects with 403
  otherwise.
- Default roles seeded per workspace on creation:
  - `owner` — everything (`*`), cannot be removed
  - `admin` — manage members, roles, invitations, jobs
  - `editor` — read, manage API keys
  - `viewer` — read-only
- Global (deployment-wide) administration — e.g. global jobs — is gated on
  the bootstrap superuser (`SUPERADMIN_EMAIL`), which does **not** bypass
  workspace-scoped checks.

## 5. Auth flows

| Flow | Mechanism |
|---|---|
| Password | `POST /auth/login` → access + refresh; `POST /auth/refresh` (rotating, hashed opaque token in DB); `POST /auth/logout` revokes |
| API keys | `Authorization: Bearer <key>`; permissions resolved per workspace |
| Identity | `GET /auth/me` → current user + workspaces + permissions + embedded `profile` (auto-created, same shape as `GET /me/profile`) |

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
| `workspaces.member.role_changed` | notify the member whose role changed |
| `workspaces.member.removed` | notify the removed member |
| `workspaces.invitation.created` | email hook for unregistered invites (TODO) |
| `workspaces.created` | provisioning/analytics hook (TODO) |
| `audit.entry.created` | persist an AuditLogEntry row |
| `apikeys.created` / `apikeys.revoked` | security/monitoring hook (TODO) |

Transient subject (core NATS, realtime fan-out, no persistence):

| Subject | Workflow |
| --- | --- |
| `notifications.created` | push to the user's WebSocket sessions |

Every user/automatic action publishes an audit event (`audit.entry.created`):
`user.register/login/token_refresh/logout`, `workspace.created/updated/deleted`,
`member.role_changed/removed`, `invitation.created/accepted/declined/revoked`,
`role.created`, `apikey.created/revoked`, `notification.acknowledged/
unacknowledged`, `job.run_*`. The audit workflow persists them (committed) to
`audit_log_entries`.

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
(whitelisted sort/filter fields per resource).

## 9. Security

- bcrypt password hashing, Fernet-encrypted secrets (versioned keys)
- CORS allowlist from env; refresh-token rotation + revocation
- Permission checks server-side on every workspace-scoped route
- No secrets in responses; API-key raw values returned once at creation

## 10. Deployment

- **Dev**: docker-compose → postgres + nats; run `make api` / `make web` from terminal
- **Container**: `infra/docker/` (multi-stage Dockerfiles)
- **Kubernetes**: `infra/helm/saas-template` (api, web, postgres optional, nats optional, ingress, secrets)
- **Cloud**: `infra/terraform/` example — AWS EKS + RDS + NATS on EKS via Helm
  (same chart used for GCP GKE / Azure AKS)
- All services 12-factor: config via env, structured logs, `/healthz` + `/readyz`
