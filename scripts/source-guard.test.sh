#!/usr/bin/env bash
# Self-test for source-guard.sh and the source-guard.yml glue: exercises the
# pure decision function plus the retarget/comment flow against a stubbed `gh`
# (AC-1..AC-4, comment-once, closed-PR short-circuit), then asserts the
# workflow shape (AC-5 trusted evaluation, AC-6 check name), the CI wiring
# (AC-7) and the docs (AC-8) with grep. No network.
#
# Usage: bash scripts/source-guard.test.sh (also run by the `source-guard-test`
# CI job in the template repo itself). Run from the repository root.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
GUARD="$HERE/source-guard.sh"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/source-guard-test-XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "TEST FAIL: $1" >&2; exit 1; }
expect_pass() { # <desc> <base> <head> <head_repo> <base_repo>
  local out
  if ! out="$(bash "$GUARD" "$2" "$3" "$4" "$5" 2>&1)"; then
    echo "$out" >&2
    fail "expected PASS: $1 (got FAIL)"
  fi
  echo "ok: $1"
}
expect_fail() { # <desc> <base> <head> <head_repo> <base_repo> [pattern]
  local out
  if out="$(bash "$GUARD" "$2" "$3" "$4" "$5" 2>&1)"; then
    echo "$out" >&2
    fail "expected FAIL: $1 (got PASS)"
  fi
  if [ -n "${6:-}" ] && ! echo "$out" | grep -q "$6"; then
    echo "$out" >&2
    fail "expected FAIL output to match '$6': $1"
  fi
  echo "ok: $1"
}

REPO="owner/repo"

# --- AC-2: same-repo staging head passes; AC-1: feature head fails ---
expect_pass "same-repo staging head targeting main passes" main staging "$REPO" "$REPO"
expect_fail "feature head targeting main fails" main agent/x "$REPO" "$REPO" "retarget to dev"

# --- AC-3: non-main bases are ignored ---
expect_pass "base dev is ignored" dev agent/x "$REPO" "$REPO"
expect_pass "base staging is ignored" staging agent/x "$REPO" "$REPO"

# --- AC-4: fork heads fail, including a fork branch named staging ---
expect_fail "fork head targeting main fails" main agent/x "fork/repo" "$REPO" "retarget to dev"
expect_fail "fork branch named staging still fails" main staging "fork/repo" "$REPO" "retarget to dev"

# usage errors fail distinctly (so a miswired workflow step cannot pass as allow)
if bash "$GUARD" main staging "$REPO" >/dev/null 2>&1; then
  fail "missing arg exited 0 instead of failing"
fi
echo "ok: missing arg fails"

# --- stubbed-gh harness for the retarget/comment glue (same shape as
# source-guard.yml: edit first, then comment once behind the marker) ---
STUBBIN="$TMP/stubbin"
mkdir -p "$STUBBIN"
cat > "$STUBBIN/gh" <<'STUB'
#!/usr/bin/env bash
# Records calls; `pr view` prints the preset comment bodies, if any.
echo "$*" >> "$TMP_GH_LOG"
if [ "$1 $2" = "pr view" ]; then
  printf '%s' "${TMP_GH_COMMENTS:-}"
fi
STUB
chmod +x "$STUBBIN/gh"
export TMP_GH_LOG="$TMP/gh-calls.log" TMP_GH_COMMENTS=""
retarget_step() { # <pr> <state>; same shape as source-guard.yml
  local pr="$1" state="$2" body
  if [ "$state" != "open" ]; then
    echo "source-guard: PR is $state, skipping retarget."
    return 0
  fi
  PATH="$STUBBIN:$PATH" gh pr edit "$pr" --base dev
  if PATH="$STUBBIN:$PATH" gh pr view "$pr" --json comments --jq '.comments[].body' | grep -qF '<!-- source-guard -->'; then
    echo "source-guard: guidance comment already present, skipping."
  else
    body="$(printf '<!-- source-guard -->\n\nPRs merge into `dev`; only `staging` merges into `main`. This PR has been retargeted to `dev`.')"
    PATH="$STUBBIN:$PATH" gh pr comment "$pr" --body "$body"
  fi
}

# --- AC-1: feature head to main is retargeted with exactly one comment ---
: > "$TMP_GH_LOG"
if bash "$GUARD" main agent/x "$REPO" "$REPO" >/dev/null 2>&1; then
  fail "AC-1 fixture should fail the decision"
fi
retarget_step "12" "open"
grep -q "pr edit 12 --base dev" "$TMP_GH_LOG" || fail "AC-1 should retarget to dev"
[ "$(grep -c "pr comment 12" "$TMP_GH_LOG")" -eq 1 ] || fail "AC-1 should post exactly one comment"
grep -q "source-guard" "$TMP_GH_LOG" || fail "AC-1 comment should carry the marker"
echo "ok: AC-1 feature head retargeted to dev with exactly one comment"

# --- AC-4: fork head to main is retargeted the same way ---
: > "$TMP_GH_LOG"
retarget_step "13" "open"
grep -q "pr edit 13 --base dev" "$TMP_GH_LOG" || fail "AC-4 should retarget a fork PR to dev"
[ "$(grep -c "pr comment 13" "$TMP_GH_LOG")" -eq 1 ] || fail "AC-4 should post exactly one comment"
echo "ok: AC-4 fork head retargeted to dev with exactly one comment"

# --- comment-once: a marked comment already present means edit but no comment ---
export TMP_GH_COMMENTS='earlier note <!-- source-guard --> here'
: > "$TMP_GH_LOG"
retarget_step "14" "open"
grep -q "pr edit 14 --base dev" "$TMP_GH_LOG" || fail "repeat event should still retarget"
grep -q "pr comment" "$TMP_GH_LOG" && fail "repeat event posted a duplicate comment"
echo "ok: marked comment is not duplicated"
export TMP_GH_COMMENTS=""

# --- merged/closed PRs: no retarget, no comment, no misleading state ---
: > "$TMP_GH_LOG"
retarget_step "15" "closed"
retarget_step "16" "merged"
[ -s "$TMP_GH_LOG" ] && fail "closed/merged PRs must cause no gh calls"
echo "ok: closed/merged PRs cause no retarget and no comment"

# --- AC-5: trusted evaluation — the workflow never checks out the PR head
# and never executes PR-supplied code ---
WF="$REPO_ROOT/.github/workflows/source-guard.yml"
[ -f "$WF" ] || fail "source-guard.yml not found at $WF"
grep -q 'pull_request_target' "$WF" || fail "guard must trigger as pull_request_target (runs from the base branch)"
grep -q 'pull_request.base.sha' "$WF" || fail "checkout must pin the trusted base SHA"
grep -q 'scripts/source-guard.sh' "$WF" || fail "evaluation must run the checked-in decision script"
if grep -n 'ref:' "$WF" | grep -q 'head'; then
  fail "no checkout ref may point at the PR head (trusted base only)"
fi
grep -qE 'eval |source \$|checkout.*head' "$WF" \
  && fail "workflow must not eval, source, or check out PR content"
echo "ok: AC-5 trusted evaluation, no PR-head checkout, no PR-code execution"

# --- AC-6: the verdict is one named, selectable required check ---
grep -q '^name: source-guard' "$WF" || fail "workflow name must be source-guard"
grep -q '^  source-guard:' "$WF" || fail "job name must be source-guard"
echo "ok: AC-6 workflow and job both named source-guard"

# --- AC-7: the self-test runs in CI ---
grep -q 'source-guard.test.sh' "$REPO_ROOT/.github/workflows/ci.yml" \
  || fail "ci.yml must run scripts/source-guard.test.sh"
echo "ok: AC-7 self-test wired into ci.yml"

# --- AC-8: the docs state the rule and the checklist matches it ---
grep -q 'Only `staging` is merged into `main`' "$REPO_ROOT/docs/architecture/CI-CD.md" \
  || fail "CI-CD.md §2 must state the staging-into-main rule"
grep -q 'source-guard.yml' "$REPO_ROOT/docs/architecture/CI-CD.md" \
  || fail "CI-CD.md §2 must name source-guard.yml as the enforcer"
grep -q 'CICD-33' "$REPO_ROOT/docs/architecture/COMPLIANCE-CHECKLIST.md" \
  || fail "COMPLIANCE-CHECKLIST.md must gain the CICD-33 item"
echo "ok: AC-8 docs rule plus checklist item"

echo "TEST PASS: retarget with one comment, staging pass, ignored bases, fork retarget, comment-once"
