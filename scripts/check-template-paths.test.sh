#!/usr/bin/env bash
# Self-test for check-template-paths.sh: builds a throwaway git repo with a
# rename, a modification and a project-owned change, then asserts the report
# announces the rename and hides the project-owned file.
#
# Usage: bash scripts/check-template-paths.test.sh (also run by the
# `template-paths` CI job in the template repo itself).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/check-template-paths-test-XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

cp "$HERE/check-template-paths.sh" "$TMP/check-template-paths-under-test.sh"
mkdir -p "$TMP/scripts"
mv "$TMP/check-template-paths-under-test.sh" "$TMP/scripts/check-template-paths.sh"
cp "$HERE/../TEMPLATE_PATHS" "$TMP/TEMPLATE_PATHS"
echo "v0.1" > "$TMP/.template-version"

cd "$TMP"
git init -q
git config user.email "test@example.com"
git config user.name "test"

mkdir -p apps/web/src/providers apps/web/src apps/web/src/project apps/api/alembic/project_versions
for i in $(seq 1 10); do echo "line $i"; done > apps/web/src/providers/accessControlProvider.ts
echo "app v1" > apps/web/src/app.ts
echo "owned v1" > apps/web/src/project/owned.ts
echo "migration v1" > apps/api/alembic/project_versions/v1.py
git add -A && git commit -qm init && git tag v0.1

git mv apps/web/src/providers/accessControlProvider.ts apps/web/src/providers/accessControl.ts
echo "line 11" >> apps/web/src/providers/accessControl.ts
echo "app v2" >> apps/web/src/app.ts
echo "owned v2" >> apps/web/src/project/owned.ts
echo "migration v2" >> apps/api/alembic/project_versions/v1.py
git add -A && git commit -qm update

OUT="$(bash scripts/check-template-paths.sh)"
echo "$OUT"

fail() { echo "TEST FAIL: $1" >&2; exit 1; }

echo "$OUT" | grep -qE "accessControlProvider\.ts -> .*accessControl\.ts" \
  || fail "rename not announced as 'old -> new'"
echo "$OUT" | grep -q "apps/web/src/app.ts" \
  || fail "changed template-owned file not listed"
echo "$OUT" | grep -q "project/owned.ts" \
  && fail "project-owned file leaked into the report"
echo "$OUT" | grep -q "project_versions/v1.py" \
  && fail "project-owned migration leaked into the report"

OUT_ARGS="$(bash scripts/check-template-paths.sh v0.1 HEAD)"
echo "$OUT_ARGS" | grep -qE "accessControlProvider\.ts -> .*accessControl\.ts" \
  || fail "explicit FROM/TO args lost the rename report"

if bash scripts/check-template-paths.sh v9.9.9 >/dev/null 2>&1; then
  fail "unknown base ref exited 0 instead of failing loudly"
fi

echo "TEST PASS: rename announced, template changes listed, project-owned hidden, bad ref fails"
