# api-domain

Paths: `apps/api/src/models/**`, `db/**`, `services/**` (except `webhooks.py`, `webhook_dispatcher.py`, `jobs.py`, `notifications.py`, owned by api-events), `secrets/**`, `seed.py`, `apps/api/alembic/**`, `apps/api/alembic.ini`, `scripts/db-check.sh`, `scripts/db-squash.sh`, `docs/MIGRATIONS.md`.

Purpose: data model, business logic called by the routers, schema migrations, demo seed data.

Entry points:
- `src/db/session.py`: `get_db` session dependency (imported by 17 files).
- `src/models/workspace.py`: workspace, member, role, invitation models (imported by 13 files).
- `src/services/workspaces.py`: workspace and membership logic.
- `src/services/auth.py`, `oauth.py`, `two_factor.py`: authentication.
- `src/seed.py`: `make api-seed`; fixtures are checked by `_check_fixtures`.
- `alembic/env.py`, `alembic/versions/`.

Conventions:
- Models are the source of truth. After a model change run `make db-new m="..."`, review the diff, commit the file.
- Services publish events through `src/events/publisher.py` (`publish_event`, `publish_audit`).
- Tests use a scratch sqlite file configured in `apps/api/tests/conftest.py`.

Pitfalls:
- Migrations: check for accidental drops, wrong nullability and missing `server_default` (`docs/MIGRATIONS.md`).
- Two migrations with the same parent produce two heads; `make db-check` fails.
- `make db-squash` is for release boundaries only.

Checks:
- `make db-check` (CI job `db-check`)
- `cd apps/api && uv run pytest -q --tb=short -p no:cacheprovider`
