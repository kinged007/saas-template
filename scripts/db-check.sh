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

echo "==> check 1/2: single migration head"
HEADS="$(uv run alembic heads 2>/dev/null | grep -c "(head)" || true)"
if [ "$HEADS" -ne 1 ]; then
  echo "FAIL: expected 1 head, found $HEADS — repoint the newer migration's down_revision"
  uv run alembic heads 2>/dev/null
  exit 1
fi
echo "    ok: single head"

echo "==> migrating scratch DB to head"
uv run alembic upgrade head >/dev/null 2>&1
echo "    ok"

echo "==> check 2/2: autogenerate must be empty"
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
echo "PASS: migration chain is clean"
