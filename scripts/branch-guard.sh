#!/usr/bin/env bash
# Branch guard for dev, staging and main (CI-CD piece 7, §7).
#
# Usage:
#   bash scripts/branch-guard.sh <branch> <before> <after> [forced] [last-checked]
#
# Checks the pushed range (<before>..<after>, first-parent) against the branch
# model, widened back to <last-checked> when given: GitHub keeps at most one
# pending run per concurrency group, so in a burst of 3+ pushes a middle queued
# run is superseded and its range is never validated. The surviving run passes
# the newest already-checked head as <last-checked> (#1878) so the gap is
# still covered. The override only widens a fast-forward pushed range
# backwards; it never masks a non-fast-forward push and never narrows.
# dev takes single-parent commits with Area:/Release-note:
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
  # Superseded queued runs (#1878): widen back to the last checked head when
  # it is a strictly older ancestor of the pushed base. Unknown, diverged,
  # equal, or newer heads keep the pushed range.
  LAST_CHECKED="${5:-}"
  if [ -n "$LAST_CHECKED" ] && [ "$LAST_CHECKED" != "$ZERO" ] \
    && [ "$LAST_CHECKED" != "$BEFORE" ] \
    && git rev-parse --verify --quiet "$LAST_CHECKED^{commit}" >/dev/null \
    && git merge-base --is-ancestor "$LAST_CHECKED" "$BEFORE"; then
    BEFORE="$LAST_CHECKED"
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
  local area_count area_value
  area_count="$(echo "$body" | grep -cE '^[[:space:]]*(\*\*)?Area:(\*\*)?[[:space:]]+[^[:space:]]' || true)"
  if [ "$area_count" -eq 0 ]; then
    fail "$sha dev rule: missing Area: line (want 'Area: <api|web|db|infra>')"
    return 1
  fi
  if [ "$area_count" -gt 1 ]; then
    fail "$sha dev rule: multiple Area: lines (want exactly one 'Area: <api|web|db|infra>')"
    return 1
  fi
  area_value="$(echo "$body" | grep -E '^[[:space:]]*(\*\*)?Area:(\*\*)?[[:space:]]+[^[:space:]]' | sed -E 's/^[[:space:]]*(\*\*)?Area:(\*\*)?[[:space:]]+//; s/[[:space:]]+$//')"
  case "$(echo "$area_value" | tr '[:upper:]' '[:lower:]')" in
    api|web|db|infra) ;;
    *)
      fail "$sha dev rule: invalid Area: '$area_value' (want 'Area: <api|web|db|infra>')"
      return 1;;
  esac
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
