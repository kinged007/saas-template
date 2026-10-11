#!/usr/bin/env bash
# Codesight drift check: the committed .codesight map must match the source.
#
# Usage:
#   npx codesight --wiki && bash scripts/codesight-check.sh   # from repo root
#
# What it does:
#   1. Compares the working tree's .codesight against HEAD's .codesight, in
#      temporary copies — the working tree is left untouched.
#   2. codesight stamps its output with the checkout directory name and with
#      dates, so those are normalized away on both sides; otherwise every
#      checkout whose directory is not named after the repo looks like drift.
#   3. .codesight/wiki/log.md is the scan run history: every scan appends an
#      entry, so it is excluded.

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

map_dir=".codesight"
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT
committed="$work_dir/committed"
current="$work_dir/current"
mkdir -p "$committed" "$current"

git archive HEAD "$map_dir" | tar -x -C "$committed"
cp -r "$map_dir" "$current"

for tree in "$committed/$map_dir" "$current/$map_dir"; do
  find "$tree" -type f -print0 | xargs -0 sed -i -E \
    -e 's/^# .+ — /# PROJECT — /' \
    -e 's/^\*\*.+\*\* is a /\*\*PROJECT\*\* is a /' \
    -e 's/^> \*\*Last scanned:\*\*.+/> **Last scanned:** STAMP/' \
    -e 's/20[0-9]{2}-[0-9]{2}-[0-9]{2}/YYYY-MM-DD/g'
done

rm -f "$committed/$map_dir/wiki/log.md" "$current/$map_dir/wiki/log.md"

if diff -r "$committed/$map_dir" "$current/$map_dir"; then
  echo "$map_dir is up to date"
else
  echo "::error::$map_dir is stale — run 'npx codesight --wiki' and commit the result" >&2
  exit 1
fi
