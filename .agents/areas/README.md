# Areas

One area per label `area:<name>`. Each area file lists paths, entry points, conventions and checks.

| Area | Label | Paths | Purpose |
| --- | --- | --- | --- |
| [api-http](api-http.md) | `area:api-http` | `apps/api/src/{main.py,container.py,settings.py,api,core,schemas}/**`, `apps/api/pyproject.toml`, `apps/api/.env.example` | FastAPI app, routers, auth dependencies, permissions, settings |
| [api-domain](api-domain.md) | `area:api-domain` | `apps/api/src/{models,db,services,secrets}/**`, `apps/api/src/seed.py`, `apps/api/alembic/**`, `scripts/db-*.sh`, `docs/MIGRATIONS.md` | SQLAlchemy models, business logic, migrations, seed data |
| [api-events](api-events.md) | `area:api-events` | `apps/api/src/{events,jobs,workflows,realtime,email}/**`, `apps/api/src/services/{webhooks,webhook_dispatcher,jobs,notifications}.py`, `docs/WEBHOOKS.md` | Event bus, event workflows, scheduled jobs, webhooks, WebSocket push, email |
| [web-app](web-app.md) | `area:web-app` | `apps/web/src/**`, `apps/web/{package.json,package-lock.json,vite.config.ts,tsconfig.json,index.html}` | Refine + shadcn/ui SPA and its unit tests |
| [web-e2e](web-e2e.md) | `area:web-e2e` | `apps/web/e2e/**`, `apps/web/playwright*.ts` | Playwright specs against a mocked API |
| [infra-ci](infra-ci.md) | `area:infra-ci` | `infra/**`, `.github/**`, `Makefile`, `scripts/{dev.py,nats.sh}`, `.pre-commit-config.yaml`, `package.json`, `package-lock.json` | Dev tooling, CI, Docker, Helm, Terraform |
| [docs-agents](docs-agents.md) | `area:docs-agents` | `docs/*.md` (except `MIGRATIONS.md`, `WEBHOOKS.md`), `README.md`, `AGENTS.md`, `UPDATES.md`, `.agents/**`, `.codesight/**`, `.claude/**`, `plans/**`, `_bmad-output/**`, `review-artifacts/**` | Documentation and agent tooling |

## Tests

`apps/api/tests/**` belongs to the area of the code a test file exercises. Exceptions: `conftest.py` and `bus_doubles.py` belong to `api-http`; `test_db_squash_script.py` to `api-domain`; `test_dev_supervisor_env.py` and `test_node_floor.py` to `infra-ci`.

## Unowned paths

- `apps/api/pyproject.toml.bak.keep`: tracked backup file, no owner.
- `LICENSE`, `.gitignore`: no owner.
