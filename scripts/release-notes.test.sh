#!/usr/bin/env bash
# Self-test for release-notes.sh: builds a throwaway git repo with labelled
# commits, an unlabelled commit, a reverted pair and a lone revert, then
# asserts the report groups by area, drops the pair, and lists the lone
# revert under Reverted and the trailer-less commit under Unlabelled.
#
# Usage: bash scripts/release-notes.test.sh (also run by the `release-notes`
# CI job in the template repo itself). No network: the fixture repo is local.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/release-notes-test-XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

cp "$HERE/release-notes.sh" "$TMP/scripts-under-test.sh"
mkdir -p "$TMP/scripts"
mv "$TMP/scripts-under-test.sh" "$TMP/scripts/release-notes.sh"

cd "$TMP"
git init -q
git config user.email "test@example.com"
git config user.name "test"
git commit -qm init --allow-empty
echo "lone target" > other.txt
git add other.txt
git commit -qm "feat(db): seed the audit table (#100)"
git tag base

commit() {  # $1=subject, $2=body (may be empty)
  echo "$1" >> file.txt
  git add file.txt
  if [ -n "$2" ]; then
    git commit -qm "$1" -m "$2"
  else
    git commit -qm "$1"
  fi
}

commit "feat(api): billable seats (#101)" "Area: api
Release-note: Seat counts now appear on the invoice."
commit "fix(web): keep the filter bar mounted (#102)" "Area: web
Release-note: The list filter no longer resets on refresh."
commit "chore: bump a dev-only pin" ""
commit "feat(api): remove the legacy export (#103)" "Area: api
Release-note: The legacy CSV export is gone."
git revert --no-edit HEAD >/dev/null
REVERT_PAIR_SHA="$(git rev-parse --short HEAD)"
# Lone revert: its target (the base commit) is outside base..head.
git revert --no-edit base >/dev/null
LONE_REVERT_SHA="$(git rev-parse --short HEAD)"
git tag head

OUT="$(bash scripts/release-notes.sh base head)"
echo "$OUT"

fail() { echo "TEST FAIL: $1" >&2; exit 1; }

echo "$OUT" | grep -q "^## Slices" || fail "missing '## Slices' heading"
echo "$OUT" | grep -q "^### api" || fail "missing '### api' section"
echo "$OUT" | grep -q "^### web" || fail "missing '### web' section"
echo "$OUT" | grep -q "^- #101 Seat counts now appear on the invoice\." \
  || fail "api note missing or misformatted"
echo "$OUT" | grep -q "^- #102 The list filter no longer resets on refresh\." \
  || fail "web note missing or misformatted"
echo "$OUT" | grep -q "^### Unlabelled" || fail "missing Unlabelled section"
echo "$OUT" | grep -q "chore: bump a dev-only pin" \
  || fail "unlabelled commit dropped silently"
echo "$OUT" | grep -q "remove the legacy export" \
  && fail "reverted slice still listed"
echo "$OUT" | grep -q "$REVERT_PAIR_SHA" \
  && fail "revert commit of an in-range pair still listed"
echo "$OUT" | grep -q "^### Reverted" || fail "missing Reverted section"
echo "$OUT" | grep -q "$LONE_REVERT_SHA" \
  || fail "lone revert (target outside range) not listed under Reverted"

EMPTY_OUT="$(bash scripts/release-notes.sh head head)"
echo "$EMPTY_OUT" | grep -q "No changes between head and head" \
  || fail "empty range does not print the no-changes line"

if bash scripts/release-notes.sh nope head >/dev/null 2>&1; then
  fail "unknown base ref exited 0 instead of failing loudly"
fi
if bash scripts/release-notes.sh >/dev/null 2>&1; then
  fail "missing args exited 0 instead of failing loudly"
fi

echo "TEST PASS: grouped by area, pair dropped, lone revert and unlabelled listed, bad refs fail"
