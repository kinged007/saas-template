#!/usr/bin/env bash
# Squash apps/api/alembic/versions/ into a single baseline revision.
#
# Usage:
#   scripts/db-squash.sh "baseline schema"    # from repo root
#
# Why: template consumers should not replay 20 migrations to stand up a
# database, and two PRs branching a migration off the same parent silently
# collide on revision id — git sees distinct filenames so there is no merge
# conflict, but `alembic upgrade head` then fails on the duplicate. One
# baseline revision makes both problems structural instead of procedural.
#
# Run at release boundaries, not per-PR: every open branch that branched
# pre-squash must repoint its down_revision to the new baseline.
#
# How it works:
#   1. Autogenerate the baseline against an empty DB, stamping it head first
#      because alembic refuses to autogenerate otherwise.
#   2. Park the old revisions aside while the baseline is proved correct.
#   3. Prove the baseline alone reproduces the schema: fresh DB, upgrade
#      head, autogenerate again, require zero op.* calls.
#   4. Prove the old chain agreed: replay it on a second scratch DB and
#      require the same zero-op result, then drop it (git keeps the history).
#
# Consumers upgrading across a squash have a deleted revision in
# alembic_version: `alembic stamp <baseline>` then `alembic upgrade head`.
# Put that stamp target in the release notes.
set -euo pipefail

cd "$(dirname "$0")/../apps/api"

MESSAGE="${1:-baseline schema}"
BASELINE_REV="0001"
VERSIONS="alembic/versions"
PARKED="$VERSIONS/.squashed-$BASELINE_REV"

if [ -n "$(git status --porcelain -- "$VERSIONS")" ]; then
  echo "FAIL: uncommitted changes under $VERSIONS — commit or stash first"
  git status --short -- "$VERSIONS"
  exit 1
fi

OLD_COUNT="$(find "$VERSIONS" -maxdepth 1 -name '*.py' | wc -l | tr -d ' ')"
if [ "$OLD_COUNT" -le 1 ]; then
  echo "SKIP: only $OLD_COUNT revision — nothing to squash"
  exit 0
fi
echo "==> squashing $OLD_COUNT revisions into $BASELINE_REV"

export EMBEDDED_DB_DIR="$(mktemp -d "${TMPDIR:-/tmp}/saas-dbsquash-XXXXXX")"
BASELINE="$VERSIONS/${BASELINE_REV}_baseline.py"
BASELINE_HOLD="$(mktemp "${TMPDIR:-/tmp}/squash-baseline-hold-XXXXXX.py")"
cleanup() {
  rm -rf "$EMBEDDED_DB_DIR" "$VERSIONS"/_squashcheck_*.py
  # If we bailed mid-verification the baseline is still on the hold path.
  [ -s "$BASELINE_HOLD" ] && mv -f "$BASELINE_HOLD" "$BASELINE" 2>/dev/null || true
  rm -f "$BASELINE_HOLD"
}
trap cleanup EXIT

fresh_db() { rm -rf "$EMBEDDED_DB_DIR"; mkdir -p "$EMBEDDED_DB_DIR"; }

echo "==> generating baseline against an empty DB"
# The empty-DB-vs-models diff is what yields the create_table calls. Stamping
# head on an empty DB only satisfies alembic's up-to-date precondition.
fresh_db
uv run alembic stamp head >/dev/null 2>&1
uv run alembic revision --autogenerate --rev-id "$BASELINE_REV" -m "$MESSAGE" >/dev/null 2>&1
GENERATED="$VERSIONS/${BASELINE_REV}_$(echo "$MESSAGE" | tr 'A-Z ' 'a-z-').py"
[ -f "$GENERATED" ] || GENERATED="$(ls -t "$VERSIONS"/*.py | head -1)"
if ! grep -qE '^[[:space:]]+op\.create_table' "$GENERATED"; then
  echo "FAIL: baseline has no create_table calls — refusing to squash"
  rm -f "$GENERATED"
  exit 1
fi
echo "    ok: $(basename "$GENERATED") ($(grep -cE '^[[:space:]]+op\.create_table' "$GENERATED") tables)"

echo "==> parking old revisions in $(basename "$PARKED")/"
mkdir -p "$PARKED"
find "$VERSIONS" -maxdepth 1 -name '*.py' -exec mv {} "$PARKED"/ \;
mv "$PARKED/$(basename "$GENERATED")" "$BASELINE"
# --rev-id names the revision but alembic still hangs the new file off the
# current head, so down_revision needs forcing to None. A baseline also has
# nothing meaningful to downgrade to; drop the stub so nobody mistakes it for
# a supported rollback path.
python3 - "$BASELINE" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p).read()
s = re.sub(r"^down_revision:.*$", "down_revision: str | None = None", s, count=1, flags=re.M)
s = re.sub(r"\n\ndef downgrade\(\).*", "\n", s, flags=re.S)
# Alembic renders custom column types by dotted path but never imports them.
# StringUUID() takes no args, so the rendered length=36 is dropped too.
s = re.sub(r"src\.db\.base\.StringUUID\(length=36\)", "StringUUID()", s)
if "StringUUID()" in s and "from src.db.base import StringUUID" not in s:
    s = s.replace("import sqlalchemy as sa\n",
                  "import sqlalchemy as sa\n\nfrom src.db.base import StringUUID\n", 1)
open(p, "w").write(s)
PY
grep -q "^down_revision: str | None = None" "$BASELINE" || {
  echo "FAIL: could not detach baseline from the old chain"; exit 1; }
if grep -qE '^[[:space:]]+[^#]*\bsrc\.' "$BASELINE"; then
  echo "FAIL: baseline still references unimported modules:"
  grep -nE '^[[:space:]]+[^#]*\bsrc\.' "$BASELINE" | head -3
  exit 1
fi
echo "    ok: $(basename "$BASELINE") installed, down_revision = None"

# Autogenerate and require zero op.* calls: the live schema already equals the
# models. Prints the stray ops on failure.
assert_no_drift() {
  local label="$1"
  local before new
  before="$(ls "$VERSIONS"/*.py | sort)"
  uv run alembic revision --autogenerate --rev-id _squashcheck -m _tmp >/dev/null 2>&1 || {
    echo "FAIL: $label — could not autogenerate, inspect manually"; return 1; }
  new="$(comm -23 <(ls "$VERSIONS"/*.py | sort) <(echo "$before") | head -1 || true)"
  if [ -z "${new:-}" ]; then
    echo "FAIL: $label — autogenerate produced no file"; return 1
  fi
  if grep -qE '^[[:space:]]+op\.' "$new"; then
    echo "FAIL: $label — schema drift:"
    grep -E '^[[:space:]]+op\.' "$new"
    return 1
  fi
  # Must go on the success path too: a leftover _squashcheck revision is a
  # second head and breaks the next `alembic upgrade head`.
  rm -f "$new"
  echo "    ok: $label"
}

echo "==> verifying 1/2: baseline alone reproduces the schema"
fresh_db
uv run alembic upgrade head >/dev/null 2>&1
assert_no_drift "baseline matches models" || { echo "       restore: git checkout -- apps/api/alembic"; exit 1; }

echo "==> verifying 2/2: the old chain produced the same schema"
fresh_db
# The baseline has to step aside entirely: its revision is also "0001" and
# 0001_initial.py is in versions/ during this replay, so alembic would see a
# duplicate revision and two heads.
mv "$BASELINE" "$BASELINE_HOLD"
mv "$PARKED"/*.py "$VERSIONS"/
uv run alembic upgrade head >/dev/null 2>&1
if ! assert_no_drift "old chain matches models"; then
  echo "       versions/ holds the old chain — restore with:"
  echo "         git checkout -- apps/api/alembic"
  exit 1
fi
# Proven equivalent, so the per-PR chain is dropped. Git keeps the history;
# only the baseline belongs in the tree.
rm -f "$VERSIONS"/*.py
rm -rf "$PARKED"
mv "$BASELINE_HOLD" "$BASELINE"

echo "PASS: $(ls "$VERSIONS"/*.py | wc -l | tr -d ' ') revision, schema verified against both chains"
echo
echo "Next:"
echo "  1. git add -A apps/api/alembic && commit"
echo "  2. Repoint open PR branches' down_revision to '$BASELINE_REV' (or drop"
echo "     their migration if the change is already in the baseline)."
echo "  3. Release notes: upgrading consumers must run"
echo "     \`alembic stamp $BASELINE_REV\` then \`alembic upgrade head\`."
