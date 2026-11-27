#!/usr/bin/env bash
# Print the release-notes slice list for a promotion PR (docs/FLEET.md, Branch model).
#
# Usage:
#   scripts/release-notes.sh BASE HEAD   # e.g. scripts/release-notes.sh main staging
#   make release-notes BASE=main HEAD=staging
#
# What it does: reads `Area:` and `Release-note:` trailers from
# `git log --no-merges BASE..HEAD` and prints markdown shaped like the
# promotion PR body (`## Slices` / `### api` / `### web` …), one bullet per
# commit grouped by area. A revert whose target is another in-range commit is
# hidden, and its target is hidden while an odd number of still-active reverts
# name it — a revert cancelled by a later revert-of-revert no longer hides its
# target, so F + revert(F) + revert(revert(F)) still lists F. A revert whose
# target is outside the range is listed under `### Reverted`. A commit with no
# `Release-note:` line is listed under `### Unlabelled` with its subject and
# SHA — never dropped silently.
#
# Exit 0 when the report prints (even when the range is empty — that is review
# input, an empty promotion). Exit non-zero only when the report cannot run:
# missing BASE/HEAD or an unknown ref.
set -euo pipefail

BASE="${1:-}"
HEAD="${2:-HEAD}"

[ -n "$BASE" ] || { echo "FAIL: usage: $0 BASE HEAD (e.g. $0 main staging)" >&2; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if ! git -C "$ROOT" rev-parse --verify --quiet "$BASE^{commit}" >/dev/null; then
  echo "FAIL: base ref '$BASE' not found" >&2
  exit 1
fi
if ! git -C "$ROOT" rev-parse --verify --quiet "$HEAD^{commit}" >/dev/null; then
  echo "FAIL: target ref '$HEAD' not found" >&2
  exit 1
fi

# One record per commit: full sha, short sha, subject, body. %x1f separates
# fields, %x1e terminates records; neither byte appears in git output otherwise.
mapfile -d $'\x1e' -t RECORDS < <(git -C "$ROOT" log --no-merges --reverse \
  --format='%H%x1f%h%x1f%s%x1f%b%x1e' "$BASE..$HEAD" 2>/dev/null || true)

echo "## Slices"

if [ "${#RECORDS[@]}" -eq 0 ] || [ -z "${RECORDS[0]:-}" ]; then
  echo ""
  echo "No changes between $BASE and $HEAD."
  exit 0
fi

trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

N="${#RECORDS[@]}"
declare -a FULL SHORT SUBJ AREA NOTE
declare -a REVERT_TARGET
for (( i = 0; i < N; i++ )); do
  # Split head/middle/tail on %x1f with parameter expansion (not read: a body
  # spans lines and read stops at the first newline). git prints a newline
  # after each record's %x1e, so later records start with one — strip it, and
  # skip the phantom record the trailing newline leaves behind.
  rec="${RECORDS[$i]}"
  rec="${rec#$'\n'}"
  case "$rec" in *$'\x1f'*) ;; *) continue;; esac
  full="${rec%%$'\x1f'*}"; tail1="${rec#*$'\x1f'}"
  short="${tail1%%$'\x1f'*}"; tail2="${tail1#*$'\x1f'}"
  subj="${tail2%%$'\x1f'*}"; body="${tail2#*$'\x1f'}"
  [ -n "$full" ] || continue
  FULL+=("$full")
  SHORT+=("$short")
  SUBJ+=("$subj")
  area=""
  note=""
  target=""
  while IFS= read -r line; do
    # Match the key case-insensitively but keep the value's original case.
    key="${line%%:*}"
    if [[ "$line" == *:* ]]; then
      val="${line#*:}"
    else
      val=""
    fi
    lowkey="$(printf '%s' "$key" | tr '[:upper:]' '[:lower:]')"
    if [ "$lowkey" = "area" ] && [ -z "$area" ]; then
      area="$(trim "$val")"
    elif [ "$lowkey" = "release-note" ] && [ -z "$note" ]; then
      candidate="$(trim "$val")"
      [ -n "$candidate" ] && note="$candidate"
    fi
    if [[ "$line" =~ This\ reverts\ commit\ ([0-9a-f]{4,40})\. ]]; then
      target="${BASH_REMATCH[1]}"
    fi
  done <<< "$body"
  AREA+=("$area")
  NOTE+=("$note")
  REVERT_TARGET+=("$target")
done
N="${#FULL[@]}"

# Hide reverted commits by parity: a revert whose target is in range is always
# hidden, and its target is hidden only while an odd number of still-active
# reverts name it. A revert cancelled by a later revert-of-revert is inactive,
# so its target comes back. A revert whose target is outside the range
# survives and is listed under Reverted, unless an odd number of still-active
# reverts name it — then the pair nets to zero and both stay hidden.
declare -a TARGET_IDX ACTIVE DROPPED
for (( i = 0; i < N; i++ )); do TARGET_IDX[$i]=-1; ACTIVE[$i]=0; DROPPED[$i]=0; done
for (( i = 0; i < N; i++ )); do
  t="${REVERT_TARGET[$i]}"
  [ -n "$t" ] || continue
  for (( j = 0; j < N; j++ )); do
    if [[ "${FULL[$j]}" == "$t"* ]]; then
      TARGET_IDX[$i]="$j"
      break
    fi
  done
done
# Latest first: a revert's target always predates it, so any later revert that
# cancels it is already decided. Every revert is measured, including one whose
# target is outside the range — it stays active while an even number of
# still-active reverts name it.
for (( i = N - 1; i >= 0; i-- )); do
  [ -n "${REVERT_TARGET[$i]}" ] || continue
  n=0
  for (( k = i + 1; k < N; k++ )); do
    if [ "${TARGET_IDX[$k]}" -eq "$i" ] && [ "${ACTIVE[$k]}" -eq 1 ]; then
      n=$((n + 1))
    fi
  done
  if [ $((n % 2)) -eq 0 ]; then
    ACTIVE[$i]=1
  fi
done
for (( i = 0; i < N; i++ )); do
  if [ -n "${REVERT_TARGET[$i]}" ]; then
    if [ "${TARGET_IDX[$i]}" -ge 0 ]; then
      DROPPED[$i]=1
    else
      # Out-of-range target: listed under Reverted unless an odd number of
      # still-active reverts name it (revert-of-revert nets to zero).
      n=0
      for (( k = 0; k < N; k++ )); do
        if [ "${TARGET_IDX[$k]}" -eq "$i" ] && [ "${ACTIVE[$k]}" -eq 1 ]; then
          n=$((n + 1))
        fi
      done
      if [ $((n % 2)) -eq 1 ]; then
        DROPPED[$i]=1
      fi
    fi
  else
    n=0
    for (( k = 0; k < N; k++ )); do
      if [ "${TARGET_IDX[$k]}" -eq "$i" ] && [ "${ACTIVE[$k]}" -eq 1 ]; then
        n=$((n + 1))
      fi
    done
    if [ $((n % 2)) -eq 1 ]; then
      DROPPED[$i]=1
    fi
  fi
done

pr_number() {
  if [[ "$1" =~ \(#([0-9]+)\)[[:space:]]*$ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  fi
}

declare -a SECTION_ORDER=()
declare -a BULLETS=()
# Sets SECTION_IDX to the index for $1, appending a new section when needed.
# (A plain assignment, not $(): command substitution runs in a subshell and
# would lose the append.)
SECTION_IDX=0
section_index() {
  local want="$1" k
  for k in "${!SECTION_ORDER[@]}"; do
    if [ "${SECTION_ORDER[$k]}" = "$want" ]; then SECTION_IDX="$k"; return 0; fi
  done
  SECTION_ORDER+=("$want")
  BULLETS+=("")
  SECTION_IDX="$((${#SECTION_ORDER[@]} - 1))"
}

add_bullet() {
  local sec="$1" bullet="$2"
  section_index "$sec"
  if [ -z "${BULLETS[$SECTION_IDX]}" ]; then
    BULLETS[$SECTION_IDX]="$bullet"
  else
    BULLETS[$SECTION_IDX]="${BULLETS[$SECTION_IDX]}
$bullet"
  fi
}

for (( i = 0; i < N; i++ )); do
  [ "${DROPPED[$i]}" -eq 0 ] || continue
  subj="${SUBJ[$i]}"
  sha7="${SHORT[$i]}"
  num="$(pr_number "$subj")"
  if [ -n "${REVERT_TARGET[$i]}" ]; then
    # Lone revert: its target is outside the range, so the revert itself
    # travels with this promotion.
    add_bullet "Reverted" "- $subj ($sha7)"
  elif [ -n "${NOTE[$i]}" ] && [ -n "${AREA[$i]}" ]; then
    if [ -n "$num" ]; then
      add_bullet "${AREA[$i]}" "- #$num ${NOTE[$i]}"
    else
      add_bullet "${AREA[$i]}" "- ${NOTE[$i]} ($sha7)"
    fi
  elif [ -n "${NOTE[$i]}" ]; then
    if [ -n "$num" ]; then
      add_bullet "Unlabelled" "- #$num ${NOTE[$i]}"
    else
      add_bullet "Unlabelled" "- ${NOTE[$i]} ($sha7)"
    fi
  else
    add_bullet "Unlabelled" "- $subj ($sha7)"
  fi
done

# Areas first (alphabetical), then Reverted, then Unlabelled — the two
# bookkeeping sections always read last.
mapfile -t AREAS < <(printf '%s\n' "${SECTION_ORDER[@]}" \
  | grep -vx -e Reverted -e Unlabelled | sort -u)
for sec in "${AREAS[@]}" Reverted Unlabelled; do
  for k in "${!SECTION_ORDER[@]}"; do
    if [ "${SECTION_ORDER[$k]}" = "$sec" ] && [ -n "${BULLETS[$k]:-}" ]; then
      echo "### $sec"
      echo "${BULLETS[$k]}"
    fi
  done
done
