# Feature Specification: Malformed identifier status contract

**Issue**: #1806  **Status**: Draft  **Areas**: none (area context missing)

## User Scenarios and Testing

### User Story 1 - Client sends a malformed resource identifier (Priority: P1)

An authenticated API client requests, modifies, or deletes a resource using an
identifier that is not a parseable unique identifier (for example a typo or a
plain string where an identifier belongs), and receives a documented,
deterministic error status instead of an internal server failure.

**Independent test**: against a running test application, issue requests with
both a plain non-identifier string and a near-miss value (correct length, one
non-hex character) on every identifier-addressed route; assert the observed
status matches the documented contract and is never 500.

**Acceptance scenarios**:

1. Given an authenticated client, When the client requests any
   identifier-addressed route with a malformed identifier, Then the response
   status matches the documented contract for that route class and is never
   500.
2. Given an authenticated client, When the client sends a malformed identifier
   in both the plain-string and near-miss shapes, Then both shapes produce the
   same status on the same route.

### User Story 2 - Client requests a well-formed but unknown identifier (Priority: P1)

An authenticated API client requests a resource with a syntactically valid
identifier that matches nothing, and receives a not-found response, so callers
cannot depend on a status difference between malformed and unknown identifiers
beyond what the contract documents.

**Independent test**: against a running test application, compare the status
for a malformed identifier with the status for a freshly generated identifier
that matches nothing on the same routes; assert the unknown-identifier status
is unchanged by this work.

**Acceptance scenarios**:

1. Given an authenticated client, When the client requests a route with a
   well-formed identifier that matches nothing, Then the response is 404.
2. Given the chosen contract, When the malformed and unknown cases are compared
   on the same route, Then the relationship between the two statuses matches
   the documented statement.

## Requirements

- **FR-001**: The system MUST never answer a malformed path identifier with an
  internal server error on any identifier-addressed route.
- **FR-002**: The system MUST continue to answer a well-formed identifier that
  matches nothing with 404 on all routes covered by the identifier test suite.
- **FR-003**: The system MUST apply one documented status contract to malformed
  identifiers on routes whose path parameter is validated as a unique
  identifier by the web framework before any data lookup runs.
  [NEEDS CLARIFICATION: should that contract be 404 everywhere (extend the
  existing not-found mapping to framework validation failures) or 422 on the
  framework-validated routes (accept the framework's request error and relax
  the tests)? Suggested answer below prefers 422.]
- **FR-004**: The identifier test suite and the documented guarantee MUST agree
  with the chosen contract, so the suite passes without weakening any assertion
  the contract does not explicitly change.
- **FR-005**: The chosen behaviour MUST be stated in one sentence in the test
  suite or module documentation, so the next reader does not rediscover the
  404-versus-422 boundary.

## Acceptance Criteria

- **AC-1**: The identifier test module passes in full in the configured
  test runner (covers FR-001, FR-003, FR-004).
- **AC-2**: The full API test job is green (covers FR-001, FR-004).
- **AC-3**: Well-formed identifiers that match nothing still return 404 on
  every route the suite covers, with no status change attributable to this work
  (covers FR-002).
- **AC-4**: No malformed identifier on any covered route returns 500
  (covers FR-001).
- **AC-5**: A one-sentence statement of the chosen malformed-identifier
  behaviour is present in the test suite or module documentation
  (covers FR-005).
- **AC-6**: If the 404-everywhere contract is chosen, unrelated request
  validation failures still return their existing statuses (covers FR-003).
- **AC-7**: If the 422-on-validated-routes contract is chosen, the relaxed test
  expectations name the route class each status applies to, so a future
  framework-validated parameter is covered by the rule rather than by a
  hard-coded list (covers FR-003, FR-004).

## Edge Cases

- Near-miss identifiers (correct length with a single non-hex character) behave
  the same as plain non-identifier strings on the same route.
- Response bodies on routes that own a specific not-found message may carry
  either the generic not-found detail or the route's own detail; the pinned
  property is the status, not the message text.
- Body-sourced identifiers already follow request-validation semantics and are
  unaffected by the path-identifier decision.
- Authentication and authorization behaviour is unchanged: only authenticated
  callers reach the identifier handling under discussion.

## Out of Scope

- Changes to unrelated routing, authorization rules, or response shapes beyond
  the status-code mismatch described here.
- A general audit of which parameters are framework-validated versus
  string-then-looked-up beyond the routes the failing tests exercise.
- New error-handling infrastructure beyond the smallest change that implements
  the chosen contract.

## Clarifications

- Q: Should a malformed identifier on a framework-validated unique-identifier
  path parameter return 404 everywhere or 422 on those routes? -> A: 422 on
  the framework-validated routes, 404 elsewhere (suggested answer chosen by
  agent; awaiting person confirmation). Rationale: the framework rejects the
  value before any lookup runs, the codebase already treats
  framework-validated identifiers as request errors in two places, and the
  issue body prefers this option absent a documented 404 promise.
