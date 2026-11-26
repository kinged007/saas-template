# api-http

Paths: `apps/api/src/main.py`, `container.py`, `settings.py`, `apps/api/src/api/**` (`routes/`, `deps.py`, `crud.py`), `apps/api/src/core/**` (`permissions.py`, `security/`, `cache.py`, `metrics.py`, `request_id.py`, `dates.py`), `apps/api/src/schemas/api.py`, `apps/api/pyproject.toml`, `apps/api/.env.example`, `apps/api/tests/conftest.py`.

Purpose: FastAPI application, one router module per resource, request authentication and authorization, Pydantic schemas, settings.

Entry points:
- `src/main.py`: app, lifespan, middleware, `include_router(..., prefix=API)` for each module in `src/api/routes/`.
- `src/container.py`: shared singletons (event bus, cipher, connection manager). Routers use these; do not create a bus per request.
- `src/api/deps.py`: current user and workspace dependencies. Workspace-scoped routes require the `X-Workspace-ID` header.
- `src/core/permissions.py`: permission catalog, `<resource>:<action>` strings, `*` grants all.

Conventions:
- All routes live under `/api/v1`; responses carry `X-API-Version` (`docs/API_VERSIONING.md`).
- New permission strings are added in `core/permissions.py`; the web `PERMISSION_MAP` in `apps/web/src/providers/accessControlProvider.ts` mirrors them.
- Environment variables are declared in `settings.py` and `.env.example`.

Pitfalls:
- `deps.py` and `settings.py` are imported by many modules; changes affect all routers.
- API keys are capped by the permissions of the principal that creates them.
- A new schema field used by the web needs a matching edit in `apps/web/src/types.ts`.

Checks (from `.github/workflows/ci.yml`):
- `cd apps/api && uv run ruff check . && uv run ruff format --check .` (`make api-lint`)
- `cd apps/api && uv run pytest -q --tb=short -p no:cacheprovider` (`make api-test`)
