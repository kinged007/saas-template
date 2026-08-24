# SaaS Template — Architecture

## 1. Purpose

This is a multi-tenant SaaS template for IAM migration: migrating applications
and configurations between **identity provider tenants** (e.g. Microsoft Entra
→ Okta, Okta → Entra) — a modern, service-oriented reference architecture.

## 2. Reference review (what this template improves on)

| Area | Typical legacy SaaS | This template |
|---|---|---|---|
| Backend | Laravel 11 + Livewire + Filament | FastAPI (async) |
| Frontend | Blade/Livewire/Filament panels | Refine.dev + Ant Design (React) |
| Tenancy | `organisations` (single level) | `workspaces` + per-workspace roles/permissions |
| Permissions | Role strings (`Editor`, `Approver`) | First-class roles + permissions, enforced in API middleware |
| IAM providers | `TenantProviderInterface` + `ProviderFactory` (Entra only) | `ProviderConnection` ABC + registry (Entra first, provider-agnostic contract) |
| Secrets | Plaintext in `tenants.secret` | Fernet-encrypted at rest |
| Events | None | Event bus abstraction: in-process (dev) / NATS JetStream (prod) |
| Realtime | None | WebSocket push for notifications |
| API | One controller parsing Livewire snapshots | Refine-compliant REST API (`/api/v1`) |
| Tests | None | pytest (service + API level) |

Legacy domain mapped: `Organisation` → `Workspace`, `Tenant` → `Connection`,
`MigrationJob`/`MigratedApp` → future `Migration` module, `Invitation` → kept.

## 3. High-level topology

```
apps/api        FastAPI service: auth, workspaces, RBAC, connections,
                applications (via provider), notifications, WS realtime.
apps/web        Refine.dev SPA (React + Antd).
apps/worker     (future) separate process for heavy migrations.
infra/          docker-compose, Dockerfiles, Helm chart, Terraform.
```

In development everything runs from the terminal (`uvicorn`, `vite dev`);
the API embeds PostgreSQL (pgserver) and NATS runs as a plain docker
container (`make nats-up`, `scripts/nats.sh`). In production the API scales
horizontally behind an ingress; NATS JetStream is the event backbone.

## 4. Domain model

```
User ──< WorkspaceMember >── Workspace (slug, name)
  │        (role_id, status)         │
  │                                  ├──< Role >──< Permission > (permissions: string set)
  │                                  ├──< Invitation > (email, role_id, token, status)
  │                                  ├──< Connection > (provider, authority, client_id,
  │                                  │     scope, encrypted secret, endpoint, status)
  │                                  └──< MigrationJob > (status machine)
  │                                        ├──< MigrationApp > (source snapshot, mapped,
  │                                        │     migrated result, status, retry_count)
  │                                        ├──< MigrationAttempt > (per execution pass)
  │                                        ├──< MigrationLogEntry > (append-only, per app)
  │                                        └──< AuditLogEntry > (immutable, workspace-wide)
  │                                          │
  │                                          └───> provider fetch: Applications
  └──< RefreshToken >──< Notification > (user_id, type, payload, acknowledged_at)
```
[text](../apps)
- **Connection** — an IAM provider tenant the user wants to migrate **from** or
  **to**. Credentials are encrypted with Fernet before storage; the raw secret
  is never returned by the API.
- **Application** — a remotely fetched resource (Entra application /
  service principal) reviewed inside a Connection. Not persisted standalone;
  fetched live through the provider abstraction.
- **MigrationJob** — a staged, reviewed and approved migration of selected
  applications between two Connections. Status: `draft → pending_approval →
  approved → queued → running → completed | failed | stopped` (failed/stopped
  jobs can be retried). Every state change is audited.
- **MigrationApp** — one selected application inside a job. Stores the
  **standardized source snapshot** (`ApplicationDetail`), the destination
  provider's mapped creation payload and the (simulated for now) migrated
  result. Per-app status: `pending → running → succeeded | failed | skipped |
  ignored`.
- **MigrationAttempt** — one execution pass (start or retry) with a summary
  of per-app outcomes.
- **MigrationLogEntry** — append-only execution log line (level, message,
  optional app/attempt scoping) rendered by the execution monitor.
- **AuditLogEntry** — immutable audit trail for every user/system action
  (actor, IP, action, details), never updated or deleted.

## 5. Multi-tenancy & RBAC

- JWT access token (15 min) carries `sub` (user id) only.
- Every workspace-scoped request sends `X-Workspace-ID: <uuid>`.
- Dependency `require_permission("connection:create")` resolves the user's
  membership + role → permission set for that workspace and rejects with 403
  otherwise.
- Default roles seeded per workspace on creation:
  - `owner` — everything (`*`), cannot be removed
  - `admin` — manage members, connections, invitations
  - `editor` — create/test connections, review applications
  - `viewer` — read-only

## 6. Auth flows

| Flow | Mechanism |
|---|---|
| Password | `POST /auth/login` → access + refresh; `POST /auth/refresh` (rotating, hashed opaque token in DB); `POST /auth/logout` revokes |
| OAuth (Microsoft, Okta) | `GET /auth/oauth/{provider}/authorize` (Authlib, PKCE) → provider → `GET /auth/oauth/{provider}/callback` exchanges code, upserts user by `(provider, subject)` + verified email, issues one-time exchange code → frontend redirect → `POST /auth/oauth/exchange` → tokens |
| Identity | `GET /auth/me` → current user + workspaces + permissions |

OAuth state is a signed JWT bound to the original `redirect_uri`.

## 7. IAM provider abstraction

```
providers/base.py    ProviderConnection (ABC)      -- contract all providers implement
providers/entra.py   EntraProviderConnection        -- Microsoft Graph (async httpx)
providers/okta.py    OktaProviderConnection         -- Okta Management API (async httpx)
providers/registry.py PROVIDER_REGISTRY + create_connection()
```

Provider setup and per-provider requirements: see `docs/providers/okta.md`
(Entra onboarding to be documented the same way).

Contract (per provider):

- `metadata()` — display name, default authority/scope/endpoint, auth grant
- `test_connection(credentials)` — obtains token, verifies access (e.g. `GET /organization` or `.default` scope probe)
- `acquire_token(credentials)` — client-credentials flow
- `list_applications(token, search, type)` — returns normalized `ApplicationSummary`
- `get_application(token, app_id)` — returns normalized `ApplicationDetail`

All providers return the **same normalized shapes**; the API layer never talks
to provider specifics. New providers = new class + registry entry.

### Cross-provider migration contract

Migration jobs rely on the same normalization for the **destination** side:

- `snapshot_from_detail(detail)` / `detail_from_snapshot(snapshot)` — serialize
  an `ApplicationDetail` into the stored `source_app_metadata` and rebuild it,
  so any registered provider can be a migration source.
- `map_application_to_destination(detail, options)` — provider method that
  translates the standardized source schema into **that provider's own
  creation payload** (pure function, no I/O). `EntraProviderConnection` emits a
  Graph `POST /applications` body; `OktaProviderConnection` emits an Okta
  `POST /api/v1/apps` body. The mock migration worker calls this to prepare
  `mapped_metadata` for every application.
- `apply_naming_template(name, options)` / `app_has_expired_credentials(detail)`
  — shared helpers used by the worker (`naming_template`, `skip_expired`).

Credentials are never copied between providers: certificates/secrets are
recreated on the destination as part of the (future) real migration workflow.

## 8. Events & pub/sub

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
- **Migration worker (mock)** — `workflows/migrations.py` opens its own DB
  session per event, records a `MigrationAttempt`, simulates a pre-flight pause
  (`MOCK_MIGRATION_PREFLIGHT_SECONDS`, default 60) and then per-application
  provider I/O (`MOCK_MIGRATION_APP_SECONDS`, default 2): mapping via the
  destination provider, a simulated create, per-app log lines and terminal
  bookkeeping. The real migration workflow will replace the simulated calls
  without touching the event contract, the state machine or the UI.
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
unacknowledged`. The audit workflow persists them (committed) to
`audit_log_entries`.

## 9. Refine compliance (API contract)

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

### Migration jobs API (`/api/v1/migrations`)

- `GET/POST /migrations` — list (Refine conventions) / create a draft job
- `GET/PATCH/DELETE /migrations/{id}` — detail / edit draft / delete draft
- `POST /migrations/{id}/apps`, `GET /migrations/{id}/apps`,
  `DELETE /migrations/{id}/apps/{app_id}` — hand-pick and snapshot
  applications from the source connection (dedupe by source app id)
- `PATCH /migrations/apps/{app_id}` — per-app review actions:
  ignore, retry (failed → pending, `retry_count++`), edit metadata
- `POST /migrations/{id}/submit|approve|reject` — approval workflow
  (approval requires `migration:approve`; approver + timestamp recorded)
- `POST /migrations/{id}/start|stop|retry` — execution control; start/retry
  publish a migration-start event
- `GET /migrations/{id}/attempts`, `/logs` (incremental `after_id` for
  polling), `/audit` — monitoring + audit trail

## 10. Security

- Argon2/bcrypt password hashing (bcrypt), Fernet-encrypted connection secrets
- CORS allowlist from env; OAuth `state` signed; refresh-token rotation + revocation
- Permission checks server-side on every workspace-scoped route
- No secrets in responses; `Connection.secret` write-only

## 11. Deployment

- **Dev**: docker-compose → postgres + nats; run `make api` / `make web` from terminal
- **Container**: `infra/docker/` (multi-stage Dockerfiles)
- **Kubernetes**: `infra/helm/saas-template` (api, web, postgres optional, nats optional, ingress, secrets)
- **Cloud**: `infra/terraform/` example — AWS EKS + RDS + NATS on EKS via Helm
  (same chart used for GCP GKE / Azure AKS)
- All services 12-factor: config via env, structured logs, `/healthz` + `/readyz`

## 12. Roadmap (not in v1)

- **Real migration workflow** — replace the mock worker's simulated provider
  calls with real destination-side create/update/delete operations
  (`map_application_to_destination` already produces the payloads)
- Credential migration (certificates/secrets recreated on the destination)
- Group/role assignment migration (`group_id`, `create_group_template`)
- Email invitations, Okta application review polish
- Dedicated worker service (`apps/worker`) for long migrations
