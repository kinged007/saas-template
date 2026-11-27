#!/usr/bin/env bash
# Self-test for db-check.sh check 1 (template + project heads): runs the real
# script with a stubbed `uv` on PATH, then asserts the check fails loudly —
# naming Alembic's error — when `alembic heads` fails, and keeps the existing
# count message for one head, three heads, or a missing branch label.
# The passing path (exactly the template + project heads) proceeds to checks
# 2-3 against a scratch DB and is covered by the real `make db-check` CI job,
# not stubbed here.
#
# Usage: bash scripts/db-check.test.sh (run from the repository root).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CHECK="$HERE/db-check.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/dbcheck-test-XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "TEST FAIL: $1" >&2; exit 1; }

# Stub uv: `alembic heads` either fails (DBCHECK_STUB_MODE=fail) or prints
# DBCHECK_STUB_HEADS (mode=heads). Any other invocation is an error so the
# test never silently exercises the real toolchain.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/uv" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "run" ] && [ "${2:-}" = "alembic" ] && [ "${3:-}" = "heads" ]; then
  if [ "${DBCHECK_STUB_MODE:-}" = "fail" ]; then
    echo "FAILED: Can't locate revision identified by 'deadbeef'" >&2
    exit 1
  fi
  printf '%s\n' "${DBCHECK_STUB_HEADS:-}"
  exit 0
fi
echo "stub uv: unexpected args: $*" >&2
exit 1
EOF
chmod +x "$TMP/bin/uv"

run_check() { # <mode> [heads] — runs db-check.sh, prints output, returns its code
  local out code
  set +e
  if [ "${1:-}" = "fail" ]; then
    out="$(DBCHECK_STUB_MODE=fail PATH="$TMP/bin:$PATH" bash "$CHECK" 2>&1)"
    code=$?
  else
    out="$(DBCHECK_STUB_MODE=heads DBCHECK_STUB_HEADS="${2:-}" PATH="$TMP/bin:$PATH" bash "$CHECK" 2>&1)"
    code=$?
  fi
  set -e
  printf '%s\n' "$out"
  return "$code"
}

# --- #1899: a failing `alembic heads` must name Alembic's error, not exit bare ---
set +e
OUT="$(run_check fail)"
CODE=$?
set -e
[ "$CODE" -ne 0 ] || fail "failing alembic heads exited 0 instead of failing"
echo "$OUT" | grep -qF "alembic heads failed" \
  || { echo "$OUT" >&2; fail "failing alembic heads did not say 'alembic heads failed'"; }
echo "$OUT" | grep -qF "Can't locate revision identified by 'deadbeef'" \
  || { echo "$OUT" >&2; fail "failing alembic heads hid Alembic's stderr"; }
echo "ok: failing alembic heads names Alembic's error"

# --- one head still fails with the existing count message ---
ONE_HEAD="a1b2c3d4e5f6 (template)"
set +e
OUT="$(run_check heads "$ONE_HEAD")"
CODE=$?
set -e
[ "$CODE" -ne 0 ] || fail "one head exited 0 instead of failing"
echo "$OUT" | grep -qF "expected exactly the template + project heads" \
  || { echo "$OUT" >&2; fail "one head lost the count message"; }
echo "ok: one head fails with the count message"

# --- three heads still fail with the existing count message ---
THREE_HEADS="a1b2c3d4e5f6 (template)
b2c3d4e5f6a7 (project)
c3d4e5f6a7b8 (project)"
set +e
OUT="$(run_check heads "$THREE_HEADS")"
CODE=$?
set -e
[ "$CODE" -ne 0 ] || fail "three heads exited 0 instead of failing"
echo "$OUT" | grep -qF "expected exactly the template + project heads" \
  || { echo "$OUT" >&2; fail "three heads lost the count message"; }
echo "ok: three heads fail with the count message"

# --- two heads with a missing branch label still fail with the count message ---
UNLABELLED="a1b2c3d4e5f6 (template)
b2c3d4e5f6a7 (template)"
set +e
OUT="$(run_check heads "$UNLABELLED")"
CODE=$?
set -e
[ "$CODE" -ne 0 ] || fail "missing project label exited 0 instead of failing"
echo "$OUT" | grep -qF "expected exactly the template + project heads" \
  || { echo "$OUT" >&2; fail "missing project label lost the count message"; }
echo "ok: missing branch label fails with the count message"

echo "TEST PASS: failing alembic heads names its error; head-count mismatches keep the count message"
