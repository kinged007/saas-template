#!/usr/bin/env bash
# Report the template-owned files an update touches, and announce renames.
#
# Usage:
#   scripts/check-template-paths.sh [FROM_REF [TO_REF]]
#
# Defaults: FROM_REF is the tag in .template-version (the last synced template
# tag), TO_REF is HEAD. The adopter records each merged tag in that file
# (docs/UPGRADING.md §2) — it is project-owned (TEMPLATE_PATHS), so template
# releases never move it. On a `template-sync/<tag>` branch the defaults
# compare the last sync against the merge.
#
# What it does: `git diff --find-renames --name-status FROM_REF TO_REF`,
# skipping the project-owned patterns in TEMPLATE_PATHS, then prints the
# changed template-owned files and an explicit `old -> new` Renames section
# (a silent rename breaks adopter imports with exit 0 — see
# docs/product/UPDATE-PATH.md §3 — so renames are announced, never just listed).
#
# Exit 0 when the report prints (even when it reports renames — this is review
# input, not a gate). Exit non-zero only when the report cannot run: missing
# TEMPLATE_PATHS, missing .template-version with no FROM_REF given, or an
# unknown ref (fetch tags first: `git fetch template --tags`).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$ROOT/TEMPLATE_PATHS"
VERSION_FILE="$ROOT/.template-version"

FROM="${1:-}"
TO="${2:-HEAD}"

if [ -z "$FROM" ]; then
  if [ ! -f "$VERSION_FILE" ]; then
    echo "FAIL: no base ref given and $VERSION_FILE is missing — record the seed tag there (docs/UPGRADING.md §1) or pass a ref explicitly" >&2
    exit 1
  fi
  FROM="$(tr -d '[:space:]' < "$VERSION_FILE")"
  if [ -z "$FROM" ]; then
    echo "FAIL: $VERSION_FILE is empty — record the last synced template tag in it" >&2
    exit 1
  fi
fi

if [ ! -f "$MANIFEST" ]; then
  echo "FAIL: $MANIFEST is missing — it lists the project-owned paths this report skips" >&2
  exit 1
fi

if ! git -C "$ROOT" rev-parse --verify --quiet "$FROM^{commit}" >/dev/null; then
  echo "FAIL: base ref '$FROM' not found — fetch tags first (derived project: \`git fetch template --tags\`)" >&2
  exit 1
fi
if ! git -C "$ROOT" rev-parse --verify --quiet "$TO^{commit}" >/dev/null; then
  echo "FAIL: target ref '$TO' not found" >&2
  exit 1
fi

EXCLUDES=()
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue;; esac
  EXCLUDES+=(":(exclude)$line")
done < "$MANIFEST"

STATUS="$(git -C "$ROOT" -c core.quotepath=false diff --find-renames --name-status "$FROM" "$TO" -- . "${EXCLUDES[@]}")"

if [ -z "$STATUS" ]; then
  echo "No template-owned files changed between $FROM and $TO."
  exit 0
fi

echo "Template-owned files changed between $FROM and $TO:"
echo "$STATUS"
echo ""

RENAMES="$(echo "$STATUS" | grep '^R' || true)"
if [ -n "$RENAMES" ]; then
  echo "Renames since $FROM — update your imports to the new paths:"
  echo "$RENAMES" | while IFS=$'\t' read -r _score old new; do
    echo "  $old -> $new"
  done
else
  echo "No renames detected."
fi
