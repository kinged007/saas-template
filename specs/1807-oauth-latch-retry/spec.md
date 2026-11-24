# Feature Specification: Failed OAuth exchange retries on repeat visit

**Issue**: #1807  **Status**: Clarified  **Areas**: (none — area context missing, see assumptions)

## User Scenarios and Testing

### User Story 1 - Failed sign-in can be retried (Priority: P1)

A person signs in via OAuth, the code-for-token exchange fails (e.g. expired or already-used code), sees a failure message with a way back to sign-in, and returns to the callback (e.g. navigating back with the same code in the address). The application retries the exchange instead of hanging on an indefinite pending state.

**Independent test**: Mock the token exchange endpoint to reject the code, load the callback with a code, observe the failure state, leave to sign-in, return to the callback with the same code, and count exchange attempts.

**Acceptance scenarios**:

1. Given a callback visit whose exchange was rejected, When the person returns to the callback with the same code, Then a second exchange attempt is sent.
2. Given a callback visit whose exchange was rejected, When the person returns to the callback with the same code, Then the page reaches the failure state with an escape back to sign-in rather than hanging on the pending state.

### User Story 2 - Failure-path regression signal is trustworthy (Priority: P1)

The team relies on the end-to-end suite on the main branch to catch regressions in the retry behaviour above. The failure-path spec produces a stable pass/fail signal across repeated full-suite runs: a green run means the retry works, a red run means the retry is broken — not that the browser served a cached page snapshot.

**Independent test**: Run the full end-to-end suite three consecutive times on the same code and observe the failure-path spec result each time.

**Acceptance scenarios**:

1. Given the retry behaviour works, When the full end-to-end suite runs three consecutive times, Then the failure-path spec passes all three times.
2. Given the retry behaviour is broken (failed exchange blocks repeat attempts), When the failure-path spec runs, Then it fails.

## Requirements

- **FR-001**: A rejected token exchange MUST release the single-use repeat-visit guard so that a repeat visit carrying the same code triggers a new exchange attempt.
- **FR-002**: A repeat visit after a rejected exchange MUST reach the terminal failure state with an escape back to sign-in; it MUST NOT hang on the pending state with no error and no escape.
- **FR-003**: The regression spec's leave-and-return round trip MUST re-execute the callback logic on the second visit (it MUST NOT be satisfiable by a restored page snapshot that replays the already-rendered failure state without sending a new exchange attempt).
- **FR-004**: The regression spec MUST assert that exactly two exchange attempts were sent across the two visits (one per visit).
- **FR-005**: The regression spec MUST NOT be deleted, skipped, or marked as expected-to-fail; the retry assertion stays enforced.

## Acceptance Criteria

- **AC-1**: After one rejected exchange followed by a leave-and-return with the same code, two exchange attempts are observed (covers FR-001, FR-004).
- **AC-2**: After one rejected exchange followed by a leave-and-return with the same code, the failure message is visible and the pending indicator is absent (covers FR-002).
- **AC-3**: The leave-and-return round trip in the spec re-executes the callback on the second visit even when the browser would otherwise restore the page from its back/forward cache; a cached restore alone cannot satisfy AC-1 (covers FR-003).
- **AC-4**: The retry assertion remains active (no skip or expected-failure marker) and the spec records, in one comment, why the chosen round-trip navigation is used so a future edit does not reintroduce a cache-restorable navigation (covers FR-005, FR-003).
- **AC-5**: The spec passes on three consecutive full end-to-end suite runs on the main branch (covers FR-001–FR-005 jointly).
- **AC-6**: If the investigation finds the guard genuinely survives a rejected exchange (e.g. the release lands after the view is torn down or a second mount reads the guard before the release), the release is corrected so it holds whether or not the view is still mounted, and the non-end-to-end suite gains a case covering release when the view is gone (covers FR-001).

## Edge Cases

- The view is torn down (user navigates away) before the rejection handler runs — the release must still take effect for the next visit.
- A successful exchange keeps its guard: a repeat visit with the same code after success must not send a second exchange.
- A repeat visit with no code after a successful exchange is treated per the existing missing-code rules, unchanged by this fix.
- A slow or never-answering exchange is governed by the existing pending-timeout fallback, unchanged by this fix.
- Development double-mount of the callback view sends only one exchange attempt per visit.

## Out of Scope

- The companion main-branch redness from malformed-identifier API assertions (tracked separately).
- Changes to the success-path guard, the pending-timeout duration, or the missing-code behaviour.
- Backend changes to the token endpoint or its error responses.
- General end-to-end infrastructure (runners, sharding, blur/timing utilities).

## Clarifications

- None open. The issue text plus the repository code settle the scope: the cause (restored page snapshot vs. surviving guard) is decided empirically by the plan/implement stage, and both branches are specified above (AC-3/AC-4 for the snapshot branch, AC-6 for the guard branch), so no scope question needs a person.
