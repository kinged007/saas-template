# Feature Specification: Nonce and browser-bound state cookie for SSO flow

**Issue**: #1864  **Status**: Clarified  **Areas**: none (area context missing)

## User Scenarios and Testing

### User Story 1 - SSO sign-in cannot be forged from another browser (Priority: P1)

A user starts SSO sign-in in their own browser. An attacker who tricks that
browser into opening a callback URL (login CSRF) cannot complete the sign-in,
because the callback is accepted only when the request also carries the
browser-bound value issued at authorization time.

**Independent test**: start an authorization request, capture the callback
parameters, then replay the callback from a client that does not hold the
issued cookie; the sign-in is rejected and no session is created.

**Acceptance scenarios**:
1. Given an SSO login was started in one browser, When the callback is
   requested without the matching browser-bound value, Then the sign-in is
   rejected and the user lands on the standard login-error outcome.
2. Given an SSO login was started in one browser, When the callback arrives
   with a browser-bound value that does not match the one issued for that
   attempt, Then the sign-in is rejected and no session, token, or account
   change results.

### User Story 2 - A captured ID token cannot be replayed into another login (Priority: P1)

A user signs in through an identity provider that returns an ID token. Each
login attempt carries a fresh unpredictable nonce, and the callback accepts
the ID token only when its nonce matches the attempt, so a token observed
from one login cannot be replayed to complete a different one.

**Independent test**: complete a callback with an ID token whose nonce is
missing or differs from the attempt's nonce; the sign-in is rejected and no
session is created.

**Acceptance scenarios**:
1. Given a login attempt issued with a nonce, When the callback presents an
   ID token with no nonce, Then the sign-in is rejected.
2. Given a login attempt issued with a nonce, When the callback presents an
   ID token with a different nonce, Then the sign-in is rejected.
3. Given a login attempt issued with a nonce, When the callback presents an
   ID token with the matching nonce and is otherwise valid, Then the login
   completes exactly as before.

## Requirements

- **FR-001**: The system MUST include a fresh, unpredictable nonce in every
  SSO authorization request.
- **FR-002**: The system MUST reject the callback when the returned ID
  token's nonce is missing or does not match the attempt's nonce, issuing no
  session, token, or one-time code.
- **FR-003**: The system MUST issue a browser-bound, single-use state value
  as a cookie at authorization time, alongside the existing server-side
  login-attempt record.
- **FR-004**: The system MUST reject the callback when the browser-bound
  cookie is missing or does not match the attempt, issuing no session,
  token, or one-time code.
- **FR-005**: Every rejection above MUST fail safe: no session is created,
  no tokens are issued, no account is created or linked, and the user sees
  the standard login-error outcome already used for invalid SSO state.
- **FR-006**: A login attempt with a matching nonce and a matching
  browser-bound value MUST complete exactly as before, including the 2FA
  challenge branch and the token-issuance branch.
- **FR-007**: Automated tests MUST cover each rejection (missing nonce,
  mismatched nonce, missing cookie, mismatched cookie) and the happy path.

## Acceptance Criteria

- **AC-1**: The authorization response redirects to the provider with a
  nonce parameter and sets the browser-bound cookie (covers FR-001, FR-003).
- **AC-2**: A callback whose ID token carries no nonce is rejected with no
  session, token, or account change (covers FR-002, FR-005).
- **AC-3**: A callback whose ID token carries a mismatched nonce is rejected
  with no session, token, or account change (covers FR-002, FR-005).
- **AC-4**: A callback without the matching browser-bound cookie is rejected
  with no session, token, or account change (covers FR-004, FR-005).
- **AC-5**: A callback with a non-matching browser-bound cookie value is
  rejected with no session, token, or account change (covers FR-004,
  FR-005).
- **AC-6**: A fully matching attempt completes login, preserving existing
  behaviour for standard sign-in and for users with 2FA enabled (covers
  FR-006).
- **AC-7**: Replaying a consumed callback (same parameters twice) is
  rejected; nonce and browser-bound values are single-use (covers FR-002,
  FR-004, FR-005).
- **AC-8**: The automated suite passes and contains one test per rejection
  in AC-2 through AC-5 plus the happy path in AC-6 (covers FR-007).

## Edge Cases

- A provider that returns no ID token (pure OAuth2): there is no token nonce
  to verify, so only the browser-bound cookie check applies.
- An expired or unknown login attempt: the existing invalid-state rejection
  applies; no new error surface is introduced.
- Plain-HTTP local development versus HTTPS deployments: the cookie Secure
  flag follows the same per-request derivation as the existing session
  cookies, so local development keeps working.
- Two concurrent login attempts: values are per attempt, so completing one
  attempt with the other attempt's values fails.
- A callback invoked twice with identical parameters: the second call is
  rejected because the attempt record is consumed on first use.

## Out of Scope

- Verified-email auto-linking, callback rate limiting, provider
  configuration validation, identities list/link/unlink, and organization
  restrictions (sibling issues under the parent epic #1845).
- Changes to password sign-in, 2FA enrolment, or session-refresh behaviour
  beyond preserving them through this flow.
- Frontend SSO buttons, provider badges, or last-used-sign-in indicators.

## Clarifications

- Q: How is a nonce or cookie failure presented to the user? -> A: Through
  the standard login-error outcome already used for invalid SSO state; no
  new error page or status code. Chosen by agent.
- Q: Where is the nonce kept between authorization and callback? -> A: Not
  prescribed; any mechanism that preserves existing behaviour is acceptable.
  Chosen by agent.
- Q: Which flags does the browser-bound cookie carry? -> A: The same
  conventions as the existing session cookies (HttpOnly, per-request Secure
  derivation, SameSite=Lax, short-lived, consumed at callback). Chosen by
  agent.
- Q: What happens for providers that return no ID token? -> A: Nonce
  verification applies only when an ID token is returned; the cookie check
  always applies. Chosen by agent.
