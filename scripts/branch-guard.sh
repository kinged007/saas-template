#!/usr/bin/env bash
# Branch guard for dev, staging and main (CI-CD piece 7, §7).
#
# Usage:
#   bash scripts/branch-guard.sh <branch> <before> <after> [forced]
#
# Checks only the pushed range (<before>..<after>, first-parent) against the
# branch model: dev takes single-parent commits with Area:/Release-note:
# trailer lines (or revert commits); staging takes merges whose second parent
# is a commit on dev; main takes merges whose second parent is reachable from
# the staging head. Any non-fast-forward push fails. Exit 0 when the range
# passes, non-zero with FAIL lines naming each offending commit and rule.
set -euo pipefail

BRANCH="${1:-}"
BEFORE="${2:-}"
AFTER="${3:-}"
FORCED="${4:-false}"
ZERO="0000000000000000000000000000000000000000"

fail() { echo "FAIL: $1" >&2; }
pass() { echo "branch-guard: PASS ($BRANCH range $BEFORE..$AFTER)"; }

case "$BRANCH" in
  dev|staging|main) ;;
  *) fail "unknown branch '$BRANCH' (want dev, staging or main)"; exit 1;;
esac

if [ -z "$BEFORE" ] || [ -z "$AFTER" ]; then
  fail "usage: branch-guard.sh <branch> <before> <after> [forced]"
  exit 1
fi

if [ "$AFTER" = "$ZERO" ]; then
  fail "branch '$BRANCH' was deleted — a missing protected branch breaks the branch model"
  exit 1
fi

if [ "$FORCED" = "true" ]; then
  fail "non-fast-forward (force) push to '$BRANCH' ($BEFORE..$AFTER)"
  exit 1
fi

if [ "$BEFORE" = "$AFTER" ]; then
  pass
  exit 0
fi

if ! git rev-parse --verify --quiet "$AFTER^{commit}" >/dev/null; then
  fail "unknown after ref '$AFTER'"
  exit 1
fi

if [ "$BEFORE" = "$ZERO" ] || ! git rev-parse --verify --quiet "$BEFORE^{commit}" >/dev/null; then
  RANGE="$(git rev-list --first-parent --reverse "$AFTER")"
else
  if ! git merge-base --is-ancestor "$BEFORE" "$AFTER"; then
    fail "non-fast-forward (force) push to '$BRANCH' ($BEFORE is not an ancestor of $AFTER)"
    exit 1
  fi
  RANGE="$(git rev-list --first-parent --reverse "$BEFORE..$AFTER")"
fi

if [ -z "$RANGE" ]; then
  pass
  exit 0
fi

resolve_head() {
  git rev-parse --verify --quiet "$1^{commit}" 2>/dev/null \
    || git rev-parse --verify --quiet "origin/$1^{commit}" 2>/dev/null \
    || echo ""
}

FAILURES=0
check_dev() {
  local sha="$1" parents body subject
  parents="$(git rev-list --parents -n1 "$sha")"
  if [ "$(echo "$parents" | wc -w)" -ne 2 ]; then
    fail "$sha dev rule: merge commit on dev (want a single-parent commit)"
    return 1
  fi
  body="$(git log -1 --format=%B "$sha")"
  subject="$(git log -1 --format=%s "$sha")"
  local lower
  lower="$(echo "$subject" | tr '[:upper:]' '[:lower:]')"
  case "$lower" in
    revert:*)
      return 0;;
  esac
  case "$subject" in
    'Revert "'*)
      return 0;;
  esac
  if ! echo "$body" | grep -qE '^[[:space:]]*(\*\*)?Area:(\*\*)?[[:space:]]+[^[:space:]]'; then
    fail "$sha dev rule: missing Area: line (want 'Area: <api|web|db|infra>')"
    return 1
  fi
  if ! echo "$body" | grep -qE '^[[:space:]]*(\*\*)?Release-note:(\*\*)?[[:space:]]+[^[:space:]]'; then
    fail "$sha dev rule: missing Release-note: line"
    return 1
  fi
  return 0
}

check_merge_parent() {
  local sha="$1" head_ref="$2" head_sha second
  second="$(git rev-list --parents -n1 "$sha" | awk '{print $3}')"
  if [ -z "$second" ]; then
    fail "$sha $BRANCH rule: not a merge commit (want a merge of $head_ref)"
    return 1
  fi
  head_sha="$(resolve_head "$head_ref")"
  if [ -z "$head_sha" ]; then
    fail "$sha $BRANCH rule: cannot resolve the $head_ref head to check parentage"
    return 1
  fi
  if ! git merge-base --is-ancestor "$second" "$head_sha"; then
    fail "$sha $BRANCH rule: second parent $second is not on $head_ref (want a merge of the $head_ref head)"
    return 1
  fi
  return 0
}

for sha in $RANGE; do
  case "$BRANCH" in
    dev) check_dev "$sha" || FAILURES=$((FAILURES + 1));;
    staging) check_merge_parent "$sha" "dev" || FAILURES=$((FAILURES + 1));;
    main) check_merge_parent "$sha" "staging" || FAILURES=$((FAILURES + 1));;
  esac
done

if [ "$FAILURES" -ne 0 ]; then
  fail "$FAILURES commit(s) break the $BRANCH branch model"
  exit 1
fi
pass
