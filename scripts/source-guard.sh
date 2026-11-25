#!/usr/bin/env bash
# Source guard for main (CI-CD §2 rule 6).
#
# Usage:
#   bash scripts/source-guard.sh <base_ref> <head_ref> <head_repo> <base_repo>
#
# Pure decision function over PR coordinates (no network, no checkout): only a
# same-repository `staging` head may target `main`. A fork branch coincidentally
# named `staging` fails — the head repo must equal the base repo. PRs whose base
# is not `main` are ignored (the workflow trigger filter already skips them;
# this is defense in depth). Exit 0 on pass or ignore, 1 on fail.
set -euo pipefail

BASE_REF="${1:-}"
HEAD_REF="${2:-}"
HEAD_REPO="${3:-}"
BASE_REPO="${4:-}"

fail() { echo "FAIL: $1" >&2; }

if [ -z "$BASE_REF" ] || [ -z "$HEAD_REF" ] || [ -z "$HEAD_REPO" ] || [ -z "$BASE_REPO" ]; then
  fail "usage: source-guard.sh <base_ref> <head_ref> <head_repo> <base_repo>"
  exit 2
fi

if [ "$BASE_REF" != "main" ]; then
  echo "source-guard: ignore (base '$BASE_REF' is not main)"
  exit 0
fi

if [ "$HEAD_REF" = "staging" ] && [ "$HEAD_REPO" = "$BASE_REPO" ]; then
  echo "source-guard: PASS (same-repo staging head targeting main)"
  exit 0
fi

fail "head '$HEAD_REF' ($HEAD_REPO) may not target main — only same-repo 'staging' merges into main; retarget to dev"
exit 1
