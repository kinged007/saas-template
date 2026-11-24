#!/usr/bin/env bash
# Promote a verified dev SHA to staging, or record a blocked promotion.
# Implements the green, red and no-op paths of docs/architecture/CI-CD.md §4.5;
# called by .github/workflows/promote.yml after the freeze and verify steps.
#
# Usage (run from the repository root; local refs dev, staging and main must
# exist — the workflow fetches them before calling):
#   RELEASE_NOTES="$(make release-notes BASE=main HEAD=staging)" \
#     bash scripts/promote.sh promote <frozen-sha> <ci-run-url> <e2e-run-url>
#   bash scripts/promote.sh blocked <frozen-sha> <ci-result> <e2e-result> <run-url>
#
# promote: exit 0 with no push, PR or issue change when staging already
#   contains the frozen SHA. Otherwise merge the SHA into staging
#   ("Promote dev@<sha7>"), push staging, and open the staging-to-main
#   promotion PR — or regenerate the open one's body.
# blocked: leave staging untouched; open (or comment on) the single
#   "Promotion blocked at <sha>" issue labelled agent:triage.
#
# Every push and gh call authenticates with GH_TOKEN, which the workflow sets
# from the FLEET_TOKEN secret. Nothing here ever writes to main.
set -euo pipefail

: "${GH_TOKEN:?promote.sh refuses to run without GH_TOKEN (the workflow sets it from the FLEET_TOKEN secret)}"

MODE="${1:-}"
case "$MODE" in
  promote|blocked) ;;
  *) echo "usage: $0 {promote|blocked} ..." >&2; exit 1 ;;
esac

short() { printf '%.7s' "$1"; }

cmd_promote() { # <frozen-sha> <ci-run-url> <e2e-run-url>
  local sha="$1" ci_url="$2" e2e_url="$3"
  local tag="dev@$(short "$sha")"
  if git merge-base --is-ancestor "$sha" staging; then
    echo "promote: staging already contains $tag; nothing to do"
    return 0
  fi
  git checkout -q staging
  git merge -q --no-ff "$sha" -m "Promote $tag"
  git push -q origin staging
  local body="## Promotion $tag -> main

CI: $ci_url | e2e: $e2e_url

Frozen SHA: $sha

${RELEASE_NOTES:-}"
  local existing
  existing="$(gh pr list --head staging --base main --state open --json number --jq '.[0].number // empty')"
  if [ -n "$existing" ]; then
    gh pr edit "$existing" --body "$body"
    echo "promote: refreshed promotion PR #$existing with $tag"
  else
    gh pr create --base main --head staging --title "Promote staging to main" --body "$body"
    echo "promote: opened the staging to main promotion PR with $tag"
  fi
}

cmd_blocked() { # <frozen-sha> <ci-result> <e2e-result> <run-url>
  local sha="$1" ci_result="$2" e2e_result="$3" run_url="$4"
  local title="Promotion blocked at $sha"
  local body="Promotion of dev@$(short "$sha") is blocked: verification failed for the frozen commit.

- ci: $ci_result ($run_url)
- e2e: $e2e_result ($run_url)

Full SHA: $sha

Re-run the promote workflow once dev is green again; it verifies the new head."
  local existing
  existing="$(gh issue list --search "$title in:title" --state open --json number --jq '.[0].number // empty')"
  if [ -n "$existing" ]; then
    gh issue comment "$existing" --body "$body"
    echo "blocked: updated issue #$existing for $sha"
  else
    gh issue create --title "$title" --label agent:triage --body "$body"
    echo "blocked: opened issue for $sha"
  fi
}

if [ "$MODE" = "promote" ]; then
  [ "$#" -eq 4 ] || { echo "usage: $0 promote <frozen-sha> <ci-run-url> <e2e-run-url>" >&2; exit 1; }
  cmd_promote "$2" "$3" "$4"
else
  [ "$#" -eq 5 ] || { echo "usage: $0 blocked <frozen-sha> <ci-result> <e2e-result> <run-url>" >&2; exit 1; }
  cmd_blocked "$2" "$3" "$4" "$5"
fi
