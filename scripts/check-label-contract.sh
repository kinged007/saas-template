#!/usr/bin/env bash
# Fleet label contract check: docs/FLEET.md must classify every
# agent:* label used in .agents/ and must not claim in-repo consumers that
# do not reference the label.
#
# Usage:
#   scripts/check-label-contract.sh   # from repo root (see `make label-contract`)
#
# What it does (see docs/FLEET.md for the contract itself):
#   1. Every agent:* label in .agents/ must appear in the doc's consumed
#      table or its starts-no-work list. Adding a label to .agents/ prose
#      without documenting it fails the check.
#   2. Every table row that cites an in-repo consumer file (a backticked
#      path that exists in the repo, optional :line suffix) must have that
#      file actually reference the label. Claiming consumption nothing
#      consumes fails the check.
set -euo pipefail

cd "$(dirname "$0")/.."

DOC=docs/FLEET.md
TABLE_HEADING='## Consumed labels'
DEAD_HEADING='## Labels that start no work'

[ -f "$DOC" ] || { echo "label-contract: missing $DOC"; exit 1; }
[ -d .agents ] || { echo "label-contract: missing .agents/"; exit 1; }

section() { # $1 = heading; prints the section body (up to the next ## heading)
  awk -v h="$1" '
    $0 == h { in_sec = 1; next }
    in_sec && /^## / { exit }
    in_sec { print }
  ' "$DOC"
}

labels_in() { grep -oE 'agent:[a-z-]+' | sort -u || true; }

agents_labels=$(grep -rhoE '(^|[^A-Za-z_])agent:[a-z-]+' .agents/ | grep -oE 'agent:[a-z-]+' | sort -u || true)
table_labels=$(section "$TABLE_HEADING" | labels_in)
dead_labels=$(section "$DEAD_HEADING" | labels_in)
fail=0

# Rule 1: every .agents/ label is classified in the doc.
for label in $agents_labels; do
  if ! printf '%s\n%s\n' "$table_labels" "$dead_labels" | grep -qx "$label"; then
    echo "label-contract: $label is used in .agents/ but is in neither the doc's consumed table nor its starts-no-work list"
    fail=1
  fi
done

# Rule 2: cited in-repo consumer files must reference the label.
section "$TABLE_HEADING" | grep -E '^\| `agent:[a-z-]+`' | while IFS= read -r row; do
  label=$(printf '%s' "$row" | grep -oE 'agent:[a-z-]+' | head -n 1)
  printf '%s' "$row" | grep -oE '`[^`]+`' | tail -n +2 | tr -d '`' | while IFS= read -r ref; do
    file=${ref%%:*}
    [ -f "$file" ] || continue
    if ! grep -q "$label" "$file"; then
      echo "label-contract: $DOC cites $ref as the consumer of $label, but it references no such label"
      exit 1
    fi
  done || exit 1
done || fail=1

exit $fail
