#!/usr/bin/env bash
# Self-test for branch-guard.sh: builds a throwaway fixture repo with
# dev/staging/main branches, then asserts the guard passes good pushes and
# fails bad ones (naming the offending SHA), plus force-push, deletion and
# range-scoping cases. Also dry-runs the workflow's open-or-update issue
# step against a stubbed gh (AC-7) without touching the network.
#
# Usage: bash scripts/branch-guard.test.sh (run from the repository root).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
GUARD="$HERE/branch-guard.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/branch-guard-test-XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "TEST FAIL: $1" >&2; exit 1; }
expect_pass() { # <desc> <branch> <before> <after>
  local out
  if ! out="$(bash "$GUARD" "$2" "$3" "$4" 2>&1)"; then
    echo "$out" >&2
    fail "expected PASS: $1 (got FAIL)"
  fi
  echo "ok: $1"
}
expect_fail() { # <desc> <branch> <before> <after> [pattern]
  local out
  if out="$(bash "$GUARD" "$2" "$3" "$4" 2>&1)"; then
    echo "$out" >&2
    fail "expected FAIL: $1 (got PASS)"
  fi
  if [ -n "${5:-}" ] && ! echo "$out" | grep -q "$5"; then
    echo "$out" >&2
    fail "expected FAIL output to match '$5': $1"
  fi
  echo "ok: $1"
}

cd "$TMP"
git init -q -b main
git config user.email "test@example.com"
git config user.name "test"
git commit -q --allow-empty -m init
git branch dev
git branch staging

# --- dev: good commits pass, trailer-less fails naming the SHA ---
git checkout -q dev
git commit -q --allow-empty -m "good slice" -m "Area: infra" -m "Release-note: one line"
GOOD_DEV="$(git rev-parse HEAD)"
BEFORE_GOOD="$(git rev-parse HEAD~1)"
expect_pass "well-formed dev commit passes" dev "$BEFORE_GOOD" "$GOOD_DEV"

git commit -q --allow-empty -m "no trailers here"
BAD_DEV="$(git rev-parse HEAD)"
expect_fail "trailer-less dev commit fails naming the SHA" dev "$GOOD_DEV" "$BAD_DEV" "$BAD_DEV"
expect_fail "range covering a historic trailer-less commit fails" dev "$BEFORE_GOOD" "$BAD_DEV" "$BAD_DEV"

# A later well-formed commit is green on its own range: the historic
# trailer-less commit is history and is never flagged again (AC-6 scoping).
git commit -q --allow-empty -m "later slice" -m "Area: api" -m "Release-note: later"
LATER_DEV="$(git rev-parse HEAD)"
expect_pass "range excluding the historic trailer-less commit passes" dev "$BAD_DEV" "$LATER_DEV"

# empty range passes
expect_pass "empty dev range passes" dev "$LATER_DEV" "$LATER_DEV"

# revert: commits pass without trailers
git commit -q --allow-empty -m "revert: broken slice"
REVERT_DEV="$(git rev-parse HEAD)"
expect_pass "revert: dev commit passes without trailers" dev "$LATER_DEV" "$REVERT_DEV"

# the VCS default revert subject passes too
git commit -q --allow-empty -m 'Revert "good slice"'
REVERT2_DEV="$(git rev-parse HEAD)"
expect_pass "default revert subject passes without trailers" dev "$REVERT_DEV" "$REVERT2_DEV"

# merge commit on dev fails the single-parent rule
git checkout -q -b side main
git commit -q --allow-empty -m "side work" -m "Area: api" -m "Release-note: side"
git checkout -q dev
git merge -q --no-ff -m "merge side" side
MERGE_ON_DEV="$(git rev-parse HEAD)"
expect_fail "merge commit on dev fails" dev "$REVERT2_DEV" "$MERGE_ON_DEV" "single-parent"

# --- staging: only dev-head merges pass ---
git checkout -q staging
git merge -q --no-ff -m "promote dev" dev
GOOD_STAGING="$(git rev-parse HEAD)"
BEFORE_STAGING="$(git rev-parse HEAD~1)"
expect_pass "staging merge of the dev head passes" staging "$BEFORE_STAGING" "$GOOD_STAGING"

git checkout -q -b rogue main
git commit -q --allow-empty -m "rogue" -m "Area: web" -m "Release-note: rogue"
git checkout -q staging
git merge -q --no-ff -m "promote rogue" rogue
BAD_STAGING="$(git rev-parse HEAD)"
expect_fail "staging merge of a non-dev branch fails naming the merge SHA" staging "$GOOD_STAGING" "$BAD_STAGING" "$BAD_STAGING"

# --- main: only staging-head merges pass ---
git checkout -q main
git merge -q --no-ff -m "release staging" staging
GOOD_MAIN="$(git rev-parse HEAD)"
BEFORE_MAIN="$(git rev-parse HEAD~1)"
expect_pass "main merge of the staging head passes" main "$BEFORE_MAIN" "$GOOD_MAIN"

# move dev forward so its tip is no longer on staging, then merge it straight
# into main: the second parent is not a staging commit, so the guard fails
git checkout -q dev
git commit -q --allow-empty -m "unpromoted slice" -m "Area: db" -m "Release-note: unpromoted"
git checkout -q main
git merge -q --no-ff -m "release dev direct" dev
BAD_MAIN="$(git rev-parse HEAD)"
expect_fail "main merge of non-staging fails naming the merge SHA" main "$GOOD_MAIN" "$BAD_MAIN" "$BAD_MAIN"

# --- force push: rewritten tip fails as non-fast-forward ---
git checkout -q dev
TIP="$(git rev-parse HEAD)"
git commit -q --allow-empty -m "fresh" -m "Area: infra" -m "Release-note: fresh"
NEWTIP="$(git rev-parse HEAD)"
REWRITTEN="$(git commit-tree "$TIP^{tree}" -p "$TIP" -m "rewritten" -m "Area: infra" -m "Release-note: rewritten")"
expect_fail "rewritten dev tip fails as non-fast-forward" dev "$NEWTIP" "$REWRITTEN" "non-fast-forward"
if bash "$GUARD" dev "$TIP" "$NEWTIP" true >/dev/null 2>&1; then
  fail "forced=true exited 0 instead of failing"
fi
echo "ok: forced=true flag fails"

# --- deletion push fails ---
expect_fail "deletion push fails" dev "$NEWTIP" "0000000000000000000000000000000000000000" "deleted"

# --- AC-7: the workflow's open-or-update issue logic updates, not duplicates ---
STUBBIN="$TMP/stubbin"
mkdir -p "$STUBBIN"
cat > "$STUBBIN/gh" <<'STUB'
#!/usr/bin/env bash
# Records calls; `issue list` reports one open violation issue when set.
echo "$*" >> "$TMP_GH_LOG"
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then
  if [ -z "${TMP_GH_EXISTING:-}" ]; then echo ""; else echo "42"; fi
fi
STUB
chmod +x "$STUBBIN/gh"
export TMP_GH_LOG="$TMP/gh-calls.log" TMP_GH_EXISTING=""
issue_step() { # same shape as branch-guard.yml: search by title prefix, comment or create
  local branch="$1" body="$2" existing
  existing="$(PATH="$STUBBIN:$PATH" gh issue list --search "[branch-guard] $branch violation in:title" --state open --json number --jq '.[0].number // empty')"
  if [ -n "$existing" ]; then
    PATH="$STUBBIN:$PATH" gh issue comment "$existing" --body "$body"
  else
    PATH="$STUBBIN:$PATH" gh issue create --title "[branch-guard] $branch violation" --label needs-human --body "$body"
  fi
}
: > "$TMP_GH_LOG"
issue_step "dev" "first violation"
grep -q "issue create" "$TMP_GH_LOG" || fail "first violation should create the issue"
export TMP_GH_EXISTING="42"
: > "$TMP_GH_LOG"
issue_step "dev" "second violation"
grep -q "issue comment 42" "$TMP_GH_LOG" || fail "second violation should comment on the open issue, not create"
grep -q "issue create" "$TMP_GH_LOG" && fail "second violation created a duplicate issue"
echo "ok: repeat violations update the open issue instead of duplicating"

# --- #1853: the workflow failure step must pass forced through, use real
# newlines, and fall back when the checkout is missing ---
WF_YML="${WF_YML:-$HERE/../.github/workflows/branch-guard.yml}"
[ -f "$WF_YML" ] || fail "branch-guard.yml not found at $WF_YML"
grep -q 'FORCED: ${{ github.event.forced }}' "$WF_YML" \
  || fail "failure step must wire FORCED from the push event"
grep -q 'branch-guard.sh "$BRANCH" "$BEFORE" "$AFTER" "$FORCED"' "$WF_YML" \
  || fail "failure step must pass \$FORCED to branch-guard.sh (forced wording)"
grep -q -- '-f scripts/branch-guard.sh' "$WF_YML" \
  || fail "failure step must guard on scripts/branch-guard.sh (missing checkout)"
grep -q "printf 'Branch" "$WF_YML" \
  || fail "failure step must build the body with printf (real newlines)"
grep -q 'BODY="Branch' "$WF_YML" \
  && fail "failure step must not use literal \\n in a double-quoted body"
echo "ok: failure step passes forced through, uses real newlines, falls back without checkout"

echo "TEST PASS: dev/staging/main good+bad, force-push, deletion, range scoping, issue update"
