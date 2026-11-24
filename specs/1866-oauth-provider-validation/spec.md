# Feature Specification: Validate OAuth providers, advertise only valid ones

**Issue**: #1866  **Status**: Clarified  **Areas**: area:config

## User Scenarios and Testing

### User Story 1 - Login shows only usable SSO options (Priority: P1)

A person opening the login page sees a single-sign-on button only for
identity providers the system can actually use, so they never start a login
flow that is doomed to fail. When nothing usable is configured, no SSO
option appears and password/registration paths are unaffected.

**Independent test**: configure a mix of valid and invalid providers, load
the login page (or read the public auth configuration), and confirm only
the valid providers appear; repeat with an empty configuration and confirm
no SSO option appears.

**Acceptance scenarios**:
1. Given one valid provider and one provider missing its secret, When the
   login page loads, Then only the valid provider's SSO option is shown.
2. Given no provider configured, When the login page loads, Then no SSO
   option is shown.

### User Story 2 - Operator learns why a provider was rejected (Priority: P1)

An operator who deploys with a misconfigured provider list finds one
startup log entry per rejected entry stating the reason, so the fix is
obvious without attempting a login.

**Independent test**: start the service once per defect class (invalid
JSON, missing credentials, duplicate ids, OIDC-style entry without an
issuer) and inspect the startup logs plus the public auth configuration.

**Acceptance scenarios**:
1. Given provider configuration that is not valid JSON, When the service
   starts, Then a log entry states the configuration could not be parsed
   and no provider is advertised.
2. Given two entries sharing one provider id, When the service starts,
   Then a log entry states the duplication and the id is advertised at
   most once.
3. Given an entry that requires an issuer but has none, When the service
   starts, Then a log entry states the missing issuer and the entry is not
   advertised.

### User Story 3 - Helm deployment configures providers through one variable (Priority: P2)

An operator installing via Helm sets the provider list through the same
`OAUTH_PROVIDERS` variable the API reads, instead of per-vendor variables
the API ignores, so Helm-deployed SSO can work at all.

**Independent test**: render the chart with OAuth values set and inspect
the rendered manifests and values schema.

**Acceptance scenarios**:
1. Given OAuth values are set in the chart, When the manifests are
   rendered, Then the API receives the provider list via `OAUTH_PROVIDERS`.
2. Given the rendered manifests, When inspected, Then no per-vendor
   variable the API never reads (`MICROSOFT_*`, `OKTA_*`) remains.

## Requirements

- **FR-001**: The system MUST validate every configured provider entry at
  startup and log one entry per rejected item stating the reason; rejected
  entries are excluded while the service still starts.
- **FR-002**: The system MUST treat a provider entry missing its client id
  or client secret as invalid.
- **FR-003**: The system MUST treat provider configuration that is not
  valid JSON (or not a list) as invalid, advertise no providers, and log
  the parse failure.
- **FR-004**: The system MUST treat duplicate provider ids as invalid and
  advertise each id at most once.
- **FR-005**: The system MUST treat an entry that requires an issuer but
  has none as invalid.
- **FR-006**: The public auth configuration MUST advertise only valid
  providers (identifier plus display name, never secrets) and MUST report
  SSO as disabled when none is valid.
- **FR-007**: The login page MUST show no SSO option when no valid provider
  is advertised.
- **FR-008**: The Helm chart MUST deliver the provider list to the API via
  `OAUTH_PROVIDERS` derived from chart values, for both the chart-managed
  secret and a user-supplied existing secret.
- **FR-009**: The Helm chart MUST NOT set per-vendor variables the API
  never reads.

## Acceptance Criteria

- **AC-1**: A provider with missing credentials is not shown on the login
  page, and startup logs state the reason (covers FR-001, FR-002, FR-007).
- **AC-2**: Invalid JSON, duplicate ids, and issuer-less OIDC-style entries
  are logged at startup and excluded from the public auth configuration
  (covers FR-001, FR-003, FR-004, FR-005, FR-006).
- **AC-3**: The Helm chart renders `OAUTH_PROVIDERS`; no unread
  `MICROSOFT_*`/`OKTA_*` variables remain (covers FR-008, FR-009).
- **AC-4**: With no provider configured, no SSO option is shown (covers
  FR-006, FR-007).

## Edge Cases

- Unset or empty provider configuration is valid-but-empty: nothing is
  advertised, SSO reports disabled, and this is not logged as an error.
- An entry with no usable identifier cannot be advertised and is logged as
  rejected.
- Non-object entries inside the provider list are skipped and logged.
- Rejection log entries MUST NOT include secret values.
- A rejected provider that is later requested directly still fails with an
  unknown/misconfigured-provider error rather than succeeding.
- Existing non-OAuth Helm behavior and values are unchanged.

## Out of Scope

- Changes to the OAuth login/callback/token flow itself.
- Adding new providers or changing issuer-discovery semantics beyond the
  missing-issuer rejection.
- Failing or refusing startup on invalid entries (rejected entries are
  excluded with a log entry; the service starts).
- Credential rotation, per-provider secret management, or login-page
  redesign.

## Clarifications

- Q: Invalid entries — fail startup fast, or exclude with a log entry? ->
  A: Exclude with a log entry; the service starts and advertises only valid
  providers (chosen by agent, per the issue text).
- Q: Duplicate ids — which occurrence wins? -> A: First valid occurrence is
  kept; later repeats are rejected and logged (chosen by agent; see
  non-blocking question q-duplicate-precedence).
- Q: Helm values shape for the provider list? -> A: One chart value
  carrying the provider list rendered as `OAUTH_PROVIDERS`; exact key
  structure left to the plan stage (chosen by agent; see non-blocking
  question q-helm-values-shape).
