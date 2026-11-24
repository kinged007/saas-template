# Feature Specification: Rate-limit failed OAuth callbacks

**Issue**: #1865  **Status**: Draft  **Areas**: (none — no area labels; area context missing)

## User Scenarios and Testing

### User Story 1 - Repeated failed SSO callbacks are throttled (Priority: P1)

An attacker (or a broken integration) replaying failing SSO callbacks from one
network address should be slowed down: after enough failures, further callback
attempts are rejected with HTTP 429 until the budget recovers.

**Independent test**: configure a tiny failure budget, trigger failing
callbacks (e.g. invalid state) from one address past the budget, and observe
HTTP 429 with a retry hint; callbacks that stay within budget still return the
normal sign-in-failed redirect.

**Acceptance scenarios**:
1. Given a fresh per-address per-provider failure budget, When failing
   callbacks arrive from one address, Then each failure consumes one unit of
   that budget.
2. Given an exhausted per-address per-provider failure budget, When another
   callback arrives from the same address for the same provider, Then the
   response is HTTP 429 with a retry hint.
3. Given failures recorded against one address and provider, When a callback
   arrives from a different address or for a different provider, Then it is
   judged against its own budget, not the exhausted one.

### User Story 2 - Successful SSO sign-ins are never throttled by this budget (Priority: P2)

A legitimate user completing SSO sign-in should not consume the failure
budget: only failed callbacks charge it.

**Independent test**: interleave successful callbacks with failures and show
the successes leave the remaining budget unchanged.

**Acceptance scenarios**:
1. Given a partially consumed failure budget, When a callback completes
   successfully (user signed in or parked for second-factor challenge), Then
   the remaining budget is unchanged.

### User Story 3 - Maintainers read an accurate throttling rule (Priority: P3)

A maintainer reading the rate-limiter rule text should learn that failed OAuth
callbacks are charged, so future route work preserves the charge.

**Independent test**: read the rule text and confirm it states that failed
callbacks consume the failure budget and which outcomes count as failures.

**Acceptance scenarios**:
1. Given the rate-limiter rule text, When read, Then it states that failed
   OAuth callbacks are charged and that successful ones are not.

## Requirements

- **FR-001**: The system MUST consume one unit of the caller's per-address
  per-provider failure budget on every failed OAuth callback (every callback
  that answers with the sign-in-failed redirect, whatever the cause: missing
  or invalid request data, expired state, provider mismatch, upstream exchange
  or identity failure, disabled registration, vanished account, or token
  issuance failure).
- **FR-002**: The system MUST keep consulting the same per-address
  per-provider budget before processing a callback, rejecting with HTTP 429
  (with a retry hint) once the budget is exhausted.
- **FR-003**: The system MUST NOT consume failure budget on a successful
  callback, including one that parks the user for a second-factor challenge.
- **FR-004**: The system MUST keep failure budgets isolated per address and
  per provider, so failures under one key do not throttle unrelated addresses
  or providers.
- **FR-005**: The rate-limiter rule text MUST describe that failed OAuth
  callbacks are charged, and distinguish charged failures from uncharged
  successes.
- **FR-006**: Automated tests MUST cover the new charging behavior: repeated
  failures from one address eventually yield HTTP 429, and successes leave
  the budget intact.

## Acceptance Criteria

- **AC-1**: Repeated failed callbacks from one address for one provider are
  eventually rejected with HTTP 429 (covers FR-001, FR-002).
- **AC-2**: The HTTP 429 carries a retry hint telling the caller when to try
  again (covers FR-002).
- **AC-3**: A successful callback (direct sign-in or second-factor park)
  does not reduce the remaining failure budget (covers FR-003).
- **AC-4**: Failures under one address/provider key do not cause HTTP 429
  for a different address or provider (covers FR-004).
- **AC-5**: The rule text states that failed OAuth callbacks consume the
  failure budget and that successful callbacks do not (covers FR-005).
- **AC-6**: Tests exist that fail if the failure charge is removed and pass
  with it present (covers FR-006).

## Edge Cases

- A callback that fails before any upstream contact (missing code/state,
  expired state) still counts as a failure and is charged.
- The registration-disabled and vanished-account redirects terminate the
  flow and count as failures, unlike the login second-factor challenge
  (different route) which intentionally leaves the budget intact.
- A second-factor-parked SSO user is a success: no charge, even though
  sign-in is not yet complete.
- Budget exhaustion timing follows the existing limiter semantics (sliding
  window plus lockout where configured); this change adds charges, not a new
  timing scheme.
- Concurrent failing callbacks from one address each consume budget; none
  may silently skip the charge.

## Out of Scope

- Changes to the authorize and token endpoints' throttling.
- Changes to budget sizes, window durations, or lockout durations.
- A shared/distributed failure store; single-process semantics stay as-is.
- Login, registration, and mail-volume budgets; only the OAuth callback
  failure budget changes.

## Clarifications

- Q: Do all callback failure exits (including registration-disabled and
  vanished-account) consume budget, or only upstream provider failures? ->
  A: All of them; every callback that answers with the sign-in-failed
  redirect is a failed callback (chosen by agent from the description
  wording "failed callbacks" plus the uniform error-redirect shape).
- Q: Is a second-factor-parked SSO callback a success (uncharged)? ->
  A: Yes; the user authenticated and the flow continues (chosen by agent).
