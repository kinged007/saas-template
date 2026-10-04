#!/usr/bin/env bash
# Migration hygiene checks: single linear head + models match migrations.
#
# Usage:
#   scripts/db-check.sh        # from repo root; uses a scratch embedded postgres
#
# What it does:
#   1. `alembic heads` must report exactly one head (catches two PRs both
#      branching a migration off the same parent).
#   2. No revision id may already exist on origin/main. Both files keep the same
#      id only in the merge result, so every other check here stays green while
#      `alembic upgrade head` breaks after merge.
#   3. Migrates a scratch DB to head, then runs
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

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/apps/api"

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

echo "==> check 2/3: no revision id reused under a different filename on main"
if git -C "$ROOT" rev-parse --verify -q origin/main >/dev/null; then
  COLLIDED=""
  for f in alembic/versions/*.py; do
    id="$(sed -nE "s/^revision(: str)? = [\"']([^\"']+).*/\2/p" "$f" | head -1)"
    [ -n "$id" ] || continue
    # Same id under any other filename is the collision; main's own files are
    # inherited as-is, so those match by name and are not reported.
    others="$(git -C "$ROOT" grep -lE "^revision(: str)? = [\"']$id[\"']\$" \
      origin/main -- apps/api/alembic/versions 2>/dev/null | sed 's#.*/##' || true)"
    for other in $others; do
      [ "$other" = "$(basename "$f")" ] || COLLIDED="$COLLIDED ${f##*/}($id)"
    done
  done
  if [ -n "$COLLIDED" ]; then
    echo "FAIL: revision id already on main under a different file:$COLLIDED"
    echo "      regenerate it: make db-new m=\"...\" (takes the id from the current head)"
    exit 1
  fi
  echo "    ok: no id collides with main"
else
  echo "    skip: origin/main not fetched"
fi

echo "==> migrating scratch DB to head"
uv run alembic upgrade head >/dev/null 2>&1
echo "    ok"

echo "==> check 3/3: autogenerate must be empty"
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
