# SaaS Template

Multi-tenant SaaS for IAM provider-to-provider migrations.

- **apps/api** — FastAPI backend (auth, workspaces, RBAC, provider connections, migration jobs, notifications, events, WebSocket)
- **apps/web** — Refine.dev + Ant Design frontend
- **infra** — Dockerfiles, Helm chart, Terraform (for production / prod-like testing)

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

## What's here

- Connect any IAM provider tenant (Entra, Okta) with encrypted credentials
- Review applications/service principals through one standardized schema
- **Migration jobs**: hand-pick applications, stage drafts, submit → approve →
  start (or reject), stop and retry, per-application ignore/retry, execution
  logs, migration attempts and a full immutable audit trail
- Execution is event-driven: `saas_template.migrations.started` is consumed by a
  mock worker (in-process bus in dev, NATS JetStream in prod) that simulates
  the per-application migration work until the real provider workflow lands.

## Quick start (development — all terminal, no docker)

The dev stack is self-contained: the API embeds PostgreSQL (via `pgserver`,
real Postgres 16 binaries, data in `~/.local/share/saas-template/pgdata`) and
consumes events asynchronously in-process. Switching to NATS JetStream is a
single env var swap (`EVENT_BUS_DRIVER=nats`).

```bash
make setup  # one-time: installs uv + Node.js if missing (tries fnm, then apt, then nvm)
make dev    # install deps, migrate, seed, then run api (:8000) + web (:5173)
```

Or run each step individually:

```bash
make api-install  # uv sync in apps/api
make api-migrate  # alembic migrations (starts embedded postgres automatically)
make api-seed     # demo user + workspace
make api          # uvicorn on :8000
make web          # vite dev on :5173 (open http://localhost:5173)
```

OpenAPI docs: http://localhost:8000/docs

Demo login (from `make api-seed`): `admin@saas-template.dev` / `Saas-template1!`

## Env

Copy `apps/api/.env.example` → `apps/api/.env` and `apps/web/.env.example` → `apps/web/.env`.
`DATABASE_URL` unset = embedded Postgres; set it to use a managed database.

## Tests

```bash
make api-test     # pytest (sqlite, in-process event bus, no docker required)
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
