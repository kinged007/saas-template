# Full-stack SaaS Starter

A production-oriented multi-tenant application starter: FastAPI + SQLAlchemy backend
and a Refine.dev (React) frontend, with workspaces, RBAC, invitations, API
keys, notifications, an event bus and framework-level scheduled jobs.

- **apps/api** — FastAPI backend (auth, workspaces, members, roles, invitations, API keys, notifications, scheduled jobs, events, WebSocket)
- **apps/web** — Refine.dev + React + shadcn/ui frontend
- **infra** — Dockerfiles, Helm chart, Terraform (for production / prod-like testing)

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

## What's here

- **Multi-tenant workspaces** — every resource is workspace-scoped; JWT auth
  plus `X-Workspace-ID` on every request
- **RBAC** — first-class roles with a permission catalog, enforced server-side
  on every workspace-scoped route; default `owner` / `admin` / `editor` /
  `viewer` roles
- **Members & invitations** — invite by email, accept/decline/revoke, role
  changes; email invitations work for unregistered users
- **API keys** — per-user keys with assignable permissions for machine access
- **Notifications** — persisted per user, pushed in realtime over WebSockets
- **Scheduled jobs** — framework-level scheduler with DB-backed definitions,
  cron schedules, missed-run policy, atomic execution, per-run params
  snapshots, and captured run logs; global and per-workspace jobs
- **Event-driven core** — domain events over an in-process bus (dev) or NATS
  JetStream (prod), with an immutable audit trail
- **Encrypted secret store** — Fernet-encrypted values at rest, behind an
  interface so a vault adapter can replace the DB implementation

## Quick start (development — all terminal, no docker)

The dev stack is self-contained: the API embeds PostgreSQL (via `pgserver`,
real Postgres 16 binaries, data in `~/.local/share/<APP_SLUG>/pgdata`) and
consumes events asynchronously in-process. Switching to NATS JetStream is a
single env var swap (`EVENT_BUS_DRIVER=nats`).

```bash
make setup  # one-time: installs uv + Node.js if missing (tries fnm, then apt, then nvm)
make dev    # install deps, migrate, seed, then run api (:8000) + web (:5173)
```

If :8000 or :5173 is already taken (e.g. another checkout's dev server), pick
other ports — the API, the Vite proxy and the cookie origin all follow:

```bash
make dev API_PORT=8010 WEB_PORT=5273   # open http://localhost:5273
```

Or run each step individually:

```bash
make api-install  # uv sync in apps/api
make api-migrate  # alembic migrations (starts embedded postgres automatically)
make api-seed     # demo users + workspaces
make api          # uvicorn on :8000 (or $API_PORT)
make web          # vite dev on :5173 (or $WEB_PORT; open http://localhost:5173)
```

OpenAPI docs: http://localhost:8000/docs

Demo logins (from `make api-seed`): all seeded users share the password
`password` — e.g. `admin@example.com` / `password` (`admin@example.com` is the dev superuser).

## Env and branding

Copy `apps/api/.env.example` → `apps/api/.env` and `apps/web/.env.example` → `apps/web/.env`.
`DATABASE_URL` unset = embedded Postgres; set it to use a managed database.

Set the same values in both files to rebrand the application:

```dotenv
# apps/api/.env
APP_NAME=My Product
APP_SLUG=my-product

# apps/web/.env
VITE_APP_NAME=My Product
VITE_APP_SLUG=my-product
VITE_LOGO_URL=/brand/logo.svg
```

`APP_SLUG` must be a lowercase DNS-style identifier. It controls the API user-config
path, embedded database directory, default NATS stream, and default NATS consumer
prefix, and refresh cookie name. The refresh cookie, an explicitly configured
`NATS_STREAM_NAME`, and Docker volumes are stateful: changing their names can
orphan existing data or sign browser sessions out. The frontend reads legacy
`tf_*` storage keys when no namespaced value exists, then writes the namespaced key.

For Docker Compose, copy `infra/docker/.env.example` to `infra/docker/.env` and set
`COMPOSE_PROJECT_NAME`, `APP_NAME`, and `APP_SLUG`; optionally set
`REFRESH_COOKIE_NAME` to retain an existing stateful cookie name. For Helm,
set `appName` and `appSlug`; build the web image with matching `VITE_APP_*` build
arguments. The reference Terraform module uses the same `app_name` and `app_slug`
variables.

## Tests

```bash
make api-test     # pytest (SQLite, in-process event bus, no docker required)
make api-test-nats  # pytest incl. real-NATS integration (skips if NATS is down)
```

## Production-like stack (optional, docker)

NATS JetStream runs as a plain docker container (no docker compose needed):

```bash
make nats-up       # start NATS JetStream (also: nats-down / nats-status / nats-logs)
make api-migrate   # alembic migrations (embedded postgres or DATABASE_URL)
EVENT_BUS_DRIVER=nats NATS_URL=nats://localhost:4222 make api
```

With a remote docker daemon (`DOCKER_HOST=tcp://…`) the published ports live on
the daemon's host — `scripts/nats.sh` prints the right `NATS_URL` to use.
