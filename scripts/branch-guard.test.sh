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
expect_pass() { # <desc> <branch> <before> <after> [last-checked]
  local out
  if ! out="$(bash "$GUARD" "$2" "$3" "$4" "false" "${5:-}" 2>&1)"; then
    echo "$out" >&2
    fail "expected PASS: $1 (got FAIL)"
  fi
  echo "ok: $1"
}
expect_fail() { # <desc> <branch> <before> <after> [pattern] [last-checked]
  local out
  if out="$(bash "$GUARD" "$2" "$3" "$4" "false" "${6:-}" 2>&1)"; then
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

# invalid Area value fails with the want-enum message (issue #1855)
git commit -q --allow-empty -m "bad area" -m "Area: mobile" -m "Release-note: bad"
BAD_AREA="$(git rev-parse HEAD)"
expect_fail "invalid Area value fails" dev "$LATER_DEV" "$BAD_AREA" "invalid Area"
expect_fail "invalid Area failure names the SHA" dev "$LATER_DEV" "$BAD_AREA" "$BAD_AREA"

# duplicate Area lines fail
git commit -q --allow-empty -m "dup area" -m "Area: api" -m "Area: web" -m "Release-note: dup"
DUP_AREA="$(git rev-parse HEAD)"
expect_fail "duplicate Area lines fail" dev "$BAD_AREA" "$DUP_AREA" "multiple Area"
expect_fail "duplicate Area failure names the SHA" dev "$BAD_AREA" "$DUP_AREA" "$DUP_AREA"

# every enum value still passes on its own range
PREV_AREA="$DUP_AREA"
for AREA in api web db infra; do
  git commit -q --allow-empty -m "area $AREA" -m "Area: $AREA" -m "Release-note: ok"
  NEXT_AREA="$(git rev-parse HEAD)"
  expect_pass "valid Area: $AREA passes" dev "$PREV_AREA" "$NEXT_AREA"
  PREV_AREA="$NEXT_AREA"
done
# re-anchor: later ranges must skip the intentionally-bad commits above
LATER_DEV="$PREV_AREA"

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

# --- #1878: the surviving run covers a superseded middle queued range ---
# Three-push burst A0 -> A1 (good), A1 -> A2 (bad), A2 -> A3 (good) where the
# middle queued run is superseded: the survivor only knows its own pushed
# range (A2..A3) plus the last checked head (A0).
R1878_BASE="$(git rev-parse HEAD)"
git commit -q --allow-empty -m "burst one" -m "Area: api" -m "Release-note: burst"
R1878_A1="$(git rev-parse HEAD)"
git commit -q --allow-empty -m "burst two has no trailers"
R1878_A2="$(git rev-parse HEAD)"
git commit -q --allow-empty -m "burst three" -m "Area: web" -m "Release-note: burst"
R1878_A3="$(git rev-parse HEAD)"
# Without the last-checked head the surviving run sees only its own pushed
# range and the middle violation slips through (the reported bug).
expect_pass "pushed-only range misses the superseded middle commit" dev "$R1878_A2" "$R1878_A3"
# With the last checked head the same run reports the middle commit.
expect_fail "widened range reports the superseded middle commit" dev "$R1878_A2" "$R1878_A3" "$R1878_A2" "$R1878_BASE"
# The override only widens: equal, already-at-head, unknown and diverged
# heads keep the pushed range, and a non-fast-forward push still fails.
expect_pass "last-checked equal to before keeps the pushed range" dev "$R1878_A2" "$R1878_A3" "$R1878_A2"
expect_pass "last-checked at after keeps the pushed range" dev "$R1878_A2" "$R1878_A3" "$R1878_A3"
expect_pass "unknown last-checked head keeps the pushed range" dev "$R1878_A2" "$R1878_A3" "0000000000000000000000000000000000000001"
git checkout -q -b drift main
git commit -q --allow-empty -m "drift" -m "Area: db" -m "Release-note: drift"
DRIFT_SHA="$(git rev-parse HEAD)"
git checkout -q dev
expect_pass "diverged last-checked head keeps the pushed range" dev "$R1878_A2" "$R1878_A3" "$DRIFT_SHA"
expect_fail "widened range still rejects a non-fast-forward push" dev "$R1878_A3" "$R1878_A1" "non-fast-forward" "$R1878_BASE"

# --- #1878 / AC-2: branch creation (zero before) and no-op cases ---
git checkout -q --orphan newborn
git commit -q --allow-empty -m "genesis" -m "Area: api" -m "Release-note: genesis"
R1878_GENESIS="$(git rev-parse HEAD)"
git checkout -q dev
ZERO40="0000000000000000000000000000000000000000"
# Zero-BEFORE checks the whole history; the last-checked head changes nothing
# on this path (a root commit never satisfies the single-parent dev rule, so
# creation reports it with or without the override).
expect_fail "branch creation checks full history" dev "$ZERO40" "$R1878_GENESIS" "$R1878_GENESIS"
expect_fail "branch creation ignores the last-checked head" dev "$ZERO40" "$R1878_GENESIS" "$R1878_GENESIS" "$R1878_BASE"
# No-op ranges still pass, with or without the override.
expect_pass "no-op range passes with last-checked set" dev "$R1878_A3" "$R1878_A3" "$R1878_BASE"

# --- #1878: the workflow resolves the last checked head and widens both
# guard invocations with it ---
grep -q 'gh run list --workflow branch-guard.yml' "$WF_YML" \
  || fail "workflow must resolve the last checked head with gh run list"
grep -q 'steps.last.outputs.sha' "$WF_YML" \
  || fail "workflow must pass the last checked head to the guard"
grep -q 'branch-guard.sh "$BRANCH" "$BEFORE" "$AFTER" "$FORCED" "$LAST"' "$WF_YML" \
  || fail "failure step must pass \$LAST to branch-guard.sh"
grep -q 'github.event.forced }}" "${{ steps.last.outputs.sha }}"' "$WF_YML" \
  || fail "guard step must pass the last checked head as the 5th arg"
echo "ok: surviving run resolves and passes the last checked head"

echo "TEST PASS: dev/staging/main good+bad, force-push, deletion, range scoping, issue update, superseded-range widening"
