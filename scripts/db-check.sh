#!/usr/bin/env bash
# Migration hygiene checks: single linear head + models match migrations.
#
# Usage:
#   scripts/db-check.sh        # from repo root; uses a scratch embedded postgres
#
# What it does:
#   1. `alembic heads` must report exactly one head (catches two PRs both
#      branching a migration off the same parent).
#   2. Migrates a scratch DB to head, then runs
#      `alembic revision --autogenerate` — the generated file must contain no
#      `op.*` calls (catches "changed models, forgot migration").
#   3. Migrates a scratch SQLite DB to head and pins the check-constraint
#      names the dialect-branched migrations land on both paths: the sqlite
#      file exercises the batch branches, the scratch postgres from checks
#      1-2 the plain ones (see docs/MIGRATIONS.md, "Dialect branches").
#
# The scratch DB is a fresh embedded postgres in a temp dir (EMBEDDED_DB_DIR),
# so this never touches your dev database.
#
# Known limitation: env.py disables compare_type/compare_server_default
# (legacy VARCHAR-vs-String spellings render as phantom drift), so silent
# column narrowings are not caught — reviewers check type changes by eye.
set -euo pipefail

cd "$(dirname "$0")/../apps/api"

export EMBEDDED_DB_DIR="$(mktemp -d "${TMPDIR:-/tmp}/saas-dbcheck-XXXXXX")"
trap 'rm -rf "$EMBEDDED_DB_DIR"' EXIT

echo "==> check 1/3: single migration head"
HEADS="$(uv run alembic heads 2>/dev/null | grep -cE '^[0-9a-f]{4,} \(head\)' || true)"
if [ "$HEADS" -ne 1 ]; then
  echo "FAIL: expected 1 head, found $HEADS — repoint the newer migration's down_revision"
  uv run alembic heads 2>/dev/null
  exit 1
fi
echo "    ok: single head"

echo "==> migrating scratch DB to head"
if ! uv run alembic upgrade head >/dev/null 2>&1; then
  echo "FAIL: postgres migration failed"
  exit 1
fi
echo "    ok"

echo "==> check 2/3: autogenerate must be empty"
BEFORE="$(ls alembic/versions/*.py)"
uv run alembic revision --autogenerate -m _dbcheck_tmp >/dev/null 2>&1
NEW="$(comm -23 <(ls alembic/versions/*.py | sort) <(echo "$BEFORE" | sort) | head -1 || true)"
if [ -z "${NEW:-}" ]; then
  echo "FAIL: autogenerate produced no file — check alembic output manually"
  exit 1
fi
if grep -qE '^[[:space:]]+op\.' "$NEW"; then
  echo "FAIL: models differ from migrations — add a migration (make db-new m=\"...\"):"
  grep -E '^[[:space:]]+op\.' "$NEW"
  rm -f "$NEW"
  exit 1
fi
rm -f "$NEW"
echo "    ok: models match migrations"

echo "==> check 3/3: constraint names on both dialect paths"
# Dialect-branched migrations take two code paths, and the naming convention
# re-applies to every name those paths pass, so a full name silently doubles.
# Autogenerate does not compare check constraints, so this pass pins the names
# the chain actually lands (see docs/MIGRATIONS.md, "Dialect branches").
export DATABASE_URL="sqlite+aiosqlite:///$EMBEDDED_DB_DIR/dbcheck-sqlite.db"
if ! uv run alembic upgrade head >/dev/null; then
  echo "FAIL: sqlite migration failed"
  exit 1
fi
uv run python - <<'PY'
import asyncio
import os

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from src.db.embedded import embedded_uri

EXPECTED = {
    "refresh_tokens": {"ck_refresh_tokens_revoke_reason"},
    "workspace_members": {"ck_workspace_members_status"},
}


async def main() -> None:
    for label, url in (
        ("sqlite batch path", f"sqlite+aiosqlite:///{os.environ['EMBEDDED_DB_DIR']}/dbcheck-sqlite.db"),
        ("postgres plain path", embedded_uri()),
    ):
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            for table, expected in EXPECTED.items():
                names = {
                    c["name"]
                    for c in await conn.run_sync(
                        lambda c, table=table: sa.inspect(c).get_check_constraints(table)
                    )
                }
                if names != expected:
                    raise SystemExit(
                        f"FAIL: {label}: {table} check constraints {sorted(names)} != {sorted(expected)} "
                        "— check-constraint ops take the bare suffix; the convention adds "
                        "ck_<table>_ (docs/MIGRATIONS.md, Dialect branches)"
                    )
                print(f"    ok: {label} {table} -> {sorted(names)}")
        await engine.dispose()


asyncio.run(main())
PY
echo "PASS: migration chain is clean"
