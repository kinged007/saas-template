#!/usr/bin/env bash
# Squash alembic/versions/ into a single baseline migration, then prove it.
#
# Usage:
#   make db-squash m="baseline schema"    # from repo root
#
# Why a baseline needs an empty database
# --------------------------------------
# `alembic revision --autogenerate` diffs the LIVE database against the
# models, not the migration chain. Diffing a database already migrated to head
# therefore yields an empty diff by construction — a "baseline" with zero
# `op.*` calls that creates nothing. And autogenerate refuses to run on a
# database with no `alembic_version` row ("Target database is not up to date"),
# because the chain's head exists and the database has never been stamped.
#
# The order that works: `alembic stamp head` writes the version row without
# executing a single migration, so the up-to-date guard passes while the
# database is still completely empty. Autogenerate then diffs empty-vs-models
# and emits the whole schema.
#
# What it does:
#   1. Generates the baseline against an empty scratch database.
#   2. Rewrites what autogenerate cannot emit correctly: `down_revision = None`
#      (it would otherwise point at the head being replaced) and the import of
#      `src.db.base` (alembic renders custom column types as a dotted path it
#      never imports). The generated `downgrade()` is kept as-is: it already
#      drops every table, which is what a baseline should do.
#   3. Proves the result twice before keeping it, each by autogenerating on a
#      fresh scratch database and requiring zero `op.*` calls: the baseline
#      alone must reproduce the schema, and the old chain must still reach it.
#   4. Replaces versions/ with the baseline.
#
# Every database is a throwaway embedded postgres in a temp dir
# (EMBEDDED_DB_DIR), so this never touches your dev database.
#
# Known limitation: env.py disables compare_type/compare_server_default
# (legacy VARCHAR-vs-String spellings render as phantom drift), so the two
# proofs below confirm tables, columns, indexes and constraints — not that
# every column kept the exact type and server default it had before. Review
# type changes in the squashed diff by eye.
#
# Refuses to run with uncommitted changes under versions/, so a squash always
# leaves one reviewable diff.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT/apps/api"
MESSAGE="${m:-baseline schema}"

if [ -n "$(git status --porcelain -- alembic/versions)" ]; then
  echo "FAIL: uncommitted changes under apps/api/alembic/versions"
  git status --porcelain -- alembic/versions
  exit 1
fi

SCRATCH_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/saas-dbsquash-XXXXXX")"
GENERATED=""
OLD_CHAIN=""

# The old chain is moved aside partway through so each proof can run with only
# one chain in versions/. That makes $SCRATCH_ROOT the last copy of it, so any
# failure has to put it back before the scratch dir is deleted.
cleanup() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    if [ -n "$OLD_CHAIN" ] && [ -d "$OLD_CHAIN" ]; then
      echo "FAIL: restoring the original chain" >&2
      rm -f alembic/versions/*.py
      cp "$OLD_CHAIN"/*.py alembic/versions/
    elif [ -n "$GENERATED" ]; then
      rm -f "alembic/versions/$(basename "$GENERATED")"
    fi
  fi
  rm -rf "$SCRATCH_ROOT"
}
trap cleanup EXIT

export EMBEDDED_DB_DIR="$SCRATCH_ROOT/pg-generate"
mkdir -p "$EMBEDDED_DB_DIR"

OLD_COUNT="$(ls alembic/versions/*.py | wc -l | tr -d ' ')"
if [ "$OLD_COUNT" -lt 1 ]; then
  echo "FAIL: no migrations in alembic/versions"
  exit 1
fi

# Autogenerate must produce a file; returns its path on stdout.
autogenerate() {
  local before after generated
  before="$(ls alembic/versions/*.py | sort)"
  uv run alembic revision --autogenerate -m "$1" >/dev/null 2>&1
  after="$(ls alembic/versions/*.py | sort)"
  generated="$(comm -13 <(echo "$before") <(echo "$after") | head -1 || true)"
  if [ -z "${generated:-}" ]; then
    echo "FAIL: autogenerate produced no file — check alembic output manually" >&2
    return 1
  fi
  echo "$generated"
}

# A schema is reproduced when autogenerating against it yields no op.* calls.
# Each check gets its own data dir: pgserver keys a running instance to it, so
# reusing one leaves a postmaster holding the old cluster.
assert_reproduces_models() {
  local label="$1" generated ops
  echo "    upgrading scratch DB to $label"
  export EMBEDDED_DB_DIR="$SCRATCH_ROOT/pg-$2"
  mkdir -p "$EMBEDDED_DB_DIR"
  uv run alembic upgrade head >/dev/null 2>&1
  generated="$(autogenerate "_squash_verify")"
  ops="$(grep -cE '^[[:space:]]+op\.' "$generated" || true)"
  if [ "${ops:-0}" -ne 0 ]; then
    echo "FAIL: $label does not reproduce the models — $ops op.* calls remain:" >&2
    grep -E '^[[:space:]]+op\.' "$generated" >&2
    rm -f "$generated"
    return 1
  fi
  rm -f "$generated"
}

echo "==> generating baseline against an empty database"
uv run alembic stamp head >/dev/null 2>&1
BASELINE="$(autogenerate "$MESSAGE")"
GENERATED="$BASELINE"
BASELINE_NAME="$(basename "$BASELINE")"
CREATE_TABLES="$(grep -cE '^[[:space:]]+op\.create_table\(' "$BASELINE" || true)"
if [ "${CREATE_TABLES:-0}" -lt 1 ]; then
  echo "FAIL: baseline has no op.create_table calls — it would create no schema" >&2
  echo "      (autogenerate diffed a non-empty database; check 'alembic stamp head' above)" >&2
  rm -f "$BASELINE"
  exit 1
fi
echo "    ok: $BASELINE_NAME ($CREATE_TABLES tables, $(wc -l <"$BASELINE" | tr -d ' ') lines)"

# Alembic renders a custom column type as the dotted path to its class and
# never emits the matching import, so the generated file would not import.
if grep -qE '^[^#]*\bsrc\.db\.base\.' "$BASELINE"; then
  echo "    rewriting src.db.base.StringUUID(length=36) -> StringUUID() + import"
  sed -i \
    -e 's/src\.db\.base\.StringUUID(length=36)/StringUUID()/g' \
    -e 's/^\(from alembic import op\)$/from alembic import op\n\nfrom src.db.base import StringUUID/' \
    "$BASELINE"
  if ! grep -qE '^from src\.db\.base import StringUUID$' "$BASELINE"; then
    echo "FAIL: could not insert the StringUUID import — inspect $BASELINE_NAME by hand" >&2
    exit 1
  fi
fi

echo "==> marking the baseline as the base revision"
python3 - "$BASELINE" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()

head, sep, body = text.partition("def upgrade() -> None:")
if not sep:
    sys.exit("FAIL: no upgrade() in the generated baseline")

header = re.sub(r"^down_revision: .*$", "down_revision: str | None = None", head, count=1, flags=re.M)
header = re.sub(r"^revision: .*$", 'revision: str = "0001"', header, count=1, flags=re.M)
header = re.sub(r"^Revision ID: .*$", "Revision ID: 0001", header, count=1, flags=re.M)
header = re.sub(r"^Revises: .*$", "Revises:", header, count=1, flags=re.M)
header = header.replace("from typing import Sequence, Union\n", "from collections.abc import Sequence\n")
header = header.replace(
    "branch_labels: Union[str, Sequence[str], None] = None",
    "branch_labels: str | Sequence[str] | None = None",
)
header = header.replace(
    "depends_on: Union[str, Sequence[str], None] = None",
    "depends_on: str | Sequence[str] | None = None",
)
path.write_text(header + sep + body)
PY
SLUG="$(echo "$MESSAGE" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_]\+/_/g; s/_*$//')"
BASELINE_NAME="0001_${SLUG:-baseline}.py"
if [ -e "alembic/versions/$BASELINE_NAME" ]; then
  echo "FAIL: alembic/versions/$BASELINE_NAME already exists — pass a different m= so the" >&2
  echo "      baseline does not overwrite an existing migration" >&2
  exit 1
fi
mv "$BASELINE" "alembic/versions/$BASELINE_NAME"
echo "    ok: $BASELINE_NAME (revision 0001, down_revision None)"

# The baseline claims revision 0001, which the old 0001 also declares, so the
# two chains can never sit in versions/ at once. Each proof below runs with
# exactly one of them in place.
OLD_CHAIN="$SCRATCH_ROOT/old-chain"
mkdir -p "$OLD_CHAIN"
mv alembic/versions/*.py "$OLD_CHAIN/"
mv "$OLD_CHAIN/$BASELINE_NAME" "$SCRATCH_ROOT/$BASELINE_NAME"
BASELINE="alembic/versions/$BASELINE_NAME"

echo "==> check 1/2: the baseline alone must reproduce the schema"
cp "$SCRATCH_ROOT/$BASELINE_NAME" alembic/versions/
assert_reproduces_models "the baseline" baseline
rm -f alembic/versions/*.py
echo "    ok"

echo "==> check 2/2: the old chain must still reach the same schema"
cp "$OLD_CHAIN"/*.py alembic/versions/
assert_reproduces_models "the old chain" old-chain
rm -f alembic/versions/*.py
echo "    ok"

echo "==> replacing versions/ with the baseline"
cp "$SCRATCH_ROOT/$BASELINE_NAME" alembic/versions/
# ruff is a dev extra: it cannot spawn without --extra dev. Lint failures
# abort the squash; the EXIT trap restores the old chain.
# Keep these ruff steps loud: do not add `>/dev/null 2>&1` here. The alembic
# steps above silence output but keep their exit codes (each has a post-check);
# a silenced ruff discarded output and failure and shipped an unformatted
# baseline (see #602). test_ruff_failure_is_not_silenced rejects it.
uv run --extra dev ruff format "$BASELINE"
uv run --extra dev ruff check --fix "$BASELINE"

echo "PASS: $OLD_COUNT migrations squashed into 1"
echo "  versions/ now holds $(ls alembic/versions/*.py | wc -l | tr -d ' ') file(s)"
echo "  review the diff, then repoint any open migration's down_revision to 0001"
echo "  consumers upgrading past this point: alembic stamp 0001 && alembic upgrade head"
