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

# Post-sync default base (#1897): the adopter records each merged tag in
# .template-version (docs/UPGRADING.md §2), so a bare run reports from the last
# merge — and the version file itself stays out of the report (project-owned).
git tag v0.2
echo "v0.2" > .template-version
git add .template-version && git commit -qm "record sync v0.2"
echo "app v3" >> apps/web/src/app.ts
git add -A && git commit -qm "post-sync template change"

OUT_SYNC="$(bash scripts/check-template-paths.sh)"
echo "$OUT_SYNC"

echo "$OUT_SYNC" | grep -q "between v0.2 and HEAD" \
  || fail "post-sync default base is not the last merged tag"
echo "$OUT_SYNC" | grep -q "apps/web/src/app.ts" \
  || fail "post-sync template change not listed"
echo "$OUT_SYNC" | grep -qE "accessControlProvider\.ts -> .*accessControl\.ts" \
  && fail "pre-sync rename leaked into the post-sync report"
echo "$OUT_SYNC" | grep -q "template-version" \
  && fail ".template-version leaked into the report (must be project-owned)"

echo "TEST PASS: rename announced, template changes listed, project-owned hidden, bad ref fails"
