#!/usr/bin/env bash
# Self-test for scripts/promote.sh and .github/workflows/promote.yml (#1873).
#
# Hermetic: throwaway git repos (a bare origin plus a work clone) and a stubbed
# `gh` on PATH, so no network is touched. Static assertions pin the workflow
# contract (schedule + manual trigger, verifier dependencies, fleet-secret
# credential, never push main); scenario assertions cover the green path
# (staging advances, one promotion PR created then updated), the red path
# (staging untouched, one blocked issue created then updated) and the no-op
# path (staging already contains the SHA: no push, PR or issue change).
#
# Usage: bash scripts/promote.test.sh (run from the repository root).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROMOTE="$HERE/promote.sh"
WORKFLOW="$HERE/../.github/workflows/promote.yml"
CI_YML="$HERE/../.github/workflows/ci.yml"
E2E_YML="$HERE/../.github/workflows/e2e.yml"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/promote-test-XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "TEST FAIL: $1" >&2; exit 1; }
ok() { echo "ok: $1"; }

[ -f "$PROMOTE" ] || fail "promote.sh not found at $PROMOTE"
[ -f "$WORKFLOW" ] || fail "promote.yml not found at $WORKFLOW"

# --- static: the workflow contract (AC-1, AC-2, AC-7, AC-8) ---
grep -q "cron: '0 4 \* \* \*'" "$WORKFLOW" \
  || fail "AC-1: promote.yml must schedule the daily 04:00 UTC run"
grep -q "workflow_dispatch" "$WORKFLOW" \
  || fail "AC-1: promote.yml must expose the workflow_dispatch trigger"
grep -q "cancel-in-progress: false" "$WORKFLOW" \
  || fail "an in-flight promotion must never be cancelled by a later run"
grep -q "needs: \[freeze, verify-ci, verify-e2e\]" "$WORKFLOW" \
  || fail "AC-2: the staging-move job must need both verifier jobs"
grep -q "uses: ./.github/workflows/ci.yml" "$WORKFLOW" \
  || fail "AC-2: promote.yml must call ci.yml as a reusable workflow"
grep -q "uses: ./.github/workflows/e2e.yml" "$WORKFLOW" \
  || fail "AC-2: promote.yml must call e2e.yml as a reusable workflow"
grep -q 'sha: ${{ needs.freeze.outputs.sha }}' "$WORKFLOW" \
  || fail "AC-2: both verifier calls must pass the frozen SHA"
grep -q 'inputs.sha' "$CI_YML" \
  || fail "AC-2: ci.yml must check out inputs.sha in every job"
grep -q 'inputs.sha' "$E2E_YML" \
  || fail "AC-2: e2e.yml must check out inputs.sha in every job"
if grep -q "GITHUB_TOKEN" "$WORKFLOW" "$PROMOTE"; then
  fail "AC-7: pushes and PR/issue calls must use FLEET_TOKEN, never the default token"
fi
grep -q "FLEET_TOKEN" "$WORKFLOW" \
  || fail "AC-7: promote.yml must authenticate with the FLEET_TOKEN secret"
if grep -n "git push" "$WORKFLOW" "$PROMOTE" | grep -v "staging"; then
  fail "AC-8: the only push target may be staging, never main"
fi
if grep -n "gh pr merge" "$WORKFLOW" "$PROMOTE"; then
  fail "AC-8: nothing may merge into main; main moves only via the maintainer"
fi
echo "ok: static workflow contract holds (schedule, dispatch, needs, fleet secret, no main push)"

# --- hermetic fixture: bare origin plus a work clone ---
export GH_TOKEN="dummy-fleet-token"
STUBBIN="$TMP/stubbin"
mkdir -p "$STUBBIN"
cat > "$STUBBIN/gh" <<'STUB'
#!/usr/bin/env bash
# Records every call; list commands report the canned open PR/issue (if any).
echo "gh $*" >> "$TMP_GH_LOG"
if [ "${1:-}" = "pr" ] && [ "${2:-}" = "list" ]; then
  [ -z "${TMP_GH_PR:-}" ] || echo "$TMP_GH_PR"
elif [ "${1:-}" = "issue" ] && [ "${2:-}" = "list" ]; then
  [ -z "${TMP_GH_ISSUE:-}" ] || echo "$TMP_GH_ISSUE"
fi
STUB
chmod +x "$STUBBIN/gh"
export PATH="$STUBBIN:$PATH"
export TMP_GH_LOG="$TMP/gh-calls.log" TMP_GH_PR="" TMP_GH_ISSUE=""
: > "$TMP_GH_LOG"

calls() { grep -cF "gh $1" "$TMP_GH_LOG" || true; }

make_fixture() {
  cd "$TMP"
  rm -rf "$TMP/origin.git" "$TMP/work"
  git init -q --bare "$TMP/origin.git"
  git clone -q "$TMP/origin.git" "$TMP/work" 2>&1 | grep -v "cloned an empty repository" >&2 || true
  (
    cd "$TMP/work"
    git config user.email "test@example.com"
    git config user.name "test"
    git checkout -q -b main
    git commit -q --allow-empty -m init
    git branch dev
    git branch staging
    git push -q origin main dev staging
  )
}

advance_dev() { # <subject> -> prints the new dev SHA
  (
    cd "$TMP/work"
    git checkout -q dev
    git commit -q --allow-empty -m "$1"
    git push -q origin dev
    git rev-parse HEAD
  )
}

origin_ref() { git --git-dir="$TMP/origin.git" rev-parse "$1"; }

# --- green path: staging advances, one PR created then updated (AC-3, AC-4) ---
make_fixture
cd "$TMP/work"
SHA1="$(advance_dev "slice one")"
SHORT1="$(printf '%.7s' "$SHA1")"
export RELEASE_NOTES="## Slices (fixture)"
bash "$PROMOTE" promote "$SHA1" "http://example.com/ci/1" "http://example.com/e2e/1"
[ "$(origin_ref staging)" = "$(git -C "$TMP/work" rev-parse staging)" ] \
  || fail "green: origin staging must match the local staging after push"
[ "$(git -C "$TMP/work" rev-parse 'staging^2')" = "$SHA1" ] \
  || fail "green: staging must merge the frozen SHA as its second parent"
git -C "$TMP/work" log -1 --format=%s staging | grep -q "Promote dev@$SHORT1" \
  || fail "green: staging head must carry the Promote dev@<sha7> message"
[ "$(calls 'pr create')" = "1" ] || fail "green: exactly one promotion PR must be created"
grep -q "pr create --base main --head staging" "$TMP_GH_LOG" \
  || fail "green: the promotion PR must run staging -> main"
grep -q "$SHA1" "$TMP_GH_LOG" || fail "AC-4: the PR body must name the frozen SHA"
grep -q "http://example.com/ci/1" "$TMP_GH_LOG" || fail "AC-4: the PR body must link the ci run"
grep -q "http://example.com/e2e/1" "$TMP_GH_LOG" || fail "AC-4: the PR body must link the e2e run"
grep -q "## Slices (fixture)" "$TMP_GH_LOG" || fail "AC-4: the PR body must contain the release notes"
[ "$(calls 'issue create')" = "0" ] || fail "green: no blocked-promotion issue may be opened"
echo "ok: green run advances staging and opens the promotion PR with SHA, run links and notes"

# A newer verified commit refreshes the open PR instead of opening another.
export TMP_GH_PR="7"
SHA2="$(advance_dev "slice two")"
SHORT2="$(printf '%.7s' "$SHA2")"
bash "$PROMOTE" promote "$SHA2" "http://example.com/ci/2" "http://example.com/e2e/2"
[ "$(git -C "$TMP/work" rev-parse 'staging^2')" = "$SHA2" ] \
  || fail "green rerun: staging must merge the newer frozen SHA"
[ "$(calls 'pr create')" = "1" ] || fail "green rerun: no second promotion PR may be opened"
[ "$(calls 'pr edit 7')" = "1" ] || fail "green rerun: the open PR must be refreshed"
grep -q "$SHA2" "$TMP_GH_LOG" || fail "green rerun: the refreshed body must name the newer SHA"
echo "ok: newer verified commit refreshes the open promotion PR instead of duplicating it"

# --- no-op path: staging already contains the SHA (AC-6) ---
BEFORE_LOG_LINES="$(wc -l < "$TMP_GH_LOG")"
BEFORE_STAGING="$(git -C "$TMP/work" rev-parse staging)"
bash "$PROMOTE" promote "$SHA2" "http://example.com/ci/2" "http://example.com/e2e/2"
[ "$(git -C "$TMP/work" rev-parse staging)" = "$BEFORE_STAGING" ] \
  || fail "no-op: staging must not move"
[ "$(wc -l < "$TMP_GH_LOG")" = "$BEFORE_LOG_LINES" ] \
  || fail "no-op: no push, PR or issue call may happen"
echo "ok: no-op run exits 0 with no push, PR or issue change"

# --- red path: staging untouched, one blocked issue created then updated (AC-5) ---
make_fixture
cd "$TMP/work"
export TMP_GH_PR=""
: > "$TMP_GH_LOG"
SHAX="$(advance_dev "doomed slice")"
STAGING_BEFORE="$(git -C "$TMP/work" rev-parse staging)"
bash "$PROMOTE" blocked "$SHAX" "failure" "success" "http://example.com/run/9"
[ "$(git -C "$TMP/work" rev-parse staging)" = "$STAGING_BEFORE" ] \
  || fail "red: staging must stay untouched"
[ "$(origin_ref staging)" = "$STAGING_BEFORE" ] \
  || fail "red: origin staging must stay untouched"
[ "$(calls 'issue create')" = "1" ] || fail "red: exactly one blocked-promotion issue must be opened"
grep -q "issue create --title Promotion blocked at $SHAX --label agent:triage" "$TMP_GH_LOG" \
  || fail "red: the blocked issue must name the SHA and route to agent:triage"
grep -q "http://example.com/run/9" "$TMP_GH_LOG" \
  || fail "red: the blocked issue must link the failed run"
[ "$(calls 'pr create')" = "0" ] && [ "$(calls 'pr edit')" = "0" ] \
  || fail "red: no promotion PR change may happen for the blocked commit"
echo "ok: red run leaves staging untouched and opens the blocked-promotion issue"

export TMP_GH_ISSUE="11"
bash "$PROMOTE" blocked "$SHAX" "failure" "failure" "http://example.com/run/10"
[ "$(calls 'issue create')" = "1" ] || fail "red rerun: no second blocked issue may be opened"
[ "$(calls 'issue comment 11')" = "1" ] \
  || fail "red rerun: the open blocked issue must be updated"
echo "ok: repeated red runs update the open blocked issue instead of duplicating it"

# --- fail closed without the fleet credential ---
cd "$TMP/work"
if env -u GH_TOKEN bash "$PROMOTE" promote "$SHAX" u u >/dev/null 2>&1; then
  fail "missing GH_TOKEN must fail instead of pushing unverified"
fi
echo "ok: missing fleet credential fails closed"

echo "promote self-test passed"
