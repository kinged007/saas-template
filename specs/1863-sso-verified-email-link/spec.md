# Feature Specification: Require verified email for SSO auto-link

**Issue**: #1863 **Status**: Draft **Areas**: (none — no `area:*` label applies; area context index is missing)

## User Scenarios and Testing

### User Story 1 — Verified SSO links to an existing account (Priority: P1)

A person with an existing account signs in through an external identity
provider that asserts the email address is verified, using the same email
address as the existing account.

**Independent test**: configure the restrictive policy, create a local
account with a verified email, then complete an SSO sign-in with the same
email and a verified assertion; the sign-in succeeds and the external
identity is linked to the existing account.

**Acceptance scenarios**:
1. Given an existing account with email E, When an SSO sign-in arrives with
   email E and the provider asserts the email is verified, Then the sign-in
   succeeds and the identity is linked to the existing account.

### User Story 2 — Unverified SSO cannot sign in or take over an account (Priority: P1)

An attacker (or a legitimate user through a provider that does not prove
mailbox control) attempts SSO with an email address that belongs to someone
else, without a verified assertion.

**Independent test**: with the restrictive policy active, create a victim
account with email E, then attempt an SSO sign-in with email E and an
unverified assertion; the sign-in fails and no link or session is created.

**Acceptance scenarios**:
1. Given an existing account with email E, When an SSO sign-in arrives with
   email E and the provider does not assert the email is verified, Then the
   sign-in fails with a generic error and no link is created.
2. Given no existing account with email E, When an SSO sign-in arrives with
   email E and the provider does not assert the email is verified [NEEDS
   CLARIFICATION: does an unverified assertion also refuse brand-new account
   creation, or only linking to an existing account?], Then the sign-in fails
   with a generic error and no account is created.

### User Story 3 — Unverified local account cannot be claimed by SSO (Priority: P1)

A password account was registered with an email address whose ownership was
never confirmed. A later SSO sign-in presents the same email address.

**Independent test**: register a password account with email E without
completing email confirmation, then attempt an SSO sign-in with email E;
the existing account is not linked or accessed.

**Acceptance scenarios**:
1. Given a password account with email E whose email is still unverified,
   When an SSO sign-in arrives with email E [NEEDS CLARIFICATION: does this
   refusal apply even when the provider asserts its email as verified, or
   only when the provider assertion is unverified?], Then the sign-in does
   not link to or grant access to that account.

### User Story 4 — Operator controls the auto-link policy with a safe default (Priority: P2)

A deployment operator reviews how automatically linking provider identities
to existing accounts behaves and adjusts it deliberately.

**Independent test**: inspect the shipped example environment file and the
effective default on a fresh deployment without setting the option; linking
without a verified assertion is refused.

**Acceptance scenarios**:
1. Given a fresh deployment with the option unset, When an unverified SSO
   sign-in targets an existing email, Then it is refused (verified-email-only
   is the default).
2. Given the documented option, When the operator reads the example
   environment file, Then the option, its default, and its effect on
   auto-linking are described there.

## Requirements

- **FR-001**: The system MUST require a provider-asserted verified email
  before an SSO sign-in links to an existing account under the default
  policy.
- **FR-002**: The system MUST refuse an SSO sign-in that does not carry a
  verified email assertion when it targets an existing account, without
  revealing whether the account exists [NEEDS CLARIFICATION: is the
  observable failure exactly the existing generic sign-in failure on the
  callback path, with no new error string and no session or token issued?].
- **FR-003**: The system MUST NOT let an SSO sign-in claim a password
  account whose email address is itself unverified [NEEDS CLARIFICATION: see
  User Story 3 — keyed on the local account state, the provider assertion,
  or both?].
- **FR-004**: The system MUST provide a configuration option controlling
  whether SSO may auto-link on unverified email, and the default MUST be
  verified-email-only [NEEDS CLARIFICATION: boolean on/off flag or a named
  policy value, and its exact option name?].
- **FR-005**: The system MUST document the option in the shipped example
  environment file, including the default and the behaviour it gates.
- **FR-006**: The system MUST treat a missing verification signal as
  unverified under the default policy [NEEDS CLARIFICATION: absent claim is
  refused the same as an explicit negative, including for providers that
  never send the signal?].
- **FR-007**: The system MUST cover each refusal above with tests.

## Acceptance Criteria

- **AC-1**: An SSO sign-in whose provider response states the email is not
  verified does not sign in and does not link to any existing account with
  the same email; the user sees only a generic sign-in failure (covers
  FR-001, FR-002).
- **AC-2**: A password account whose email is unverified is not claimed,
  linked, or accessed by a later SSO sign-in presenting the same email
  (covers FR-003).
- **AC-3**: With the option unset on a fresh deployment, the refusals in
  AC-1 and AC-2 hold (verified-email-only is the default) (covers FR-001,
  FR-004).
- **AC-4**: Setting the documented option to its permissive value restores
  the previous linking behaviour, and setting it to its restrictive value
  enforces the refusals; both positions are exercised by tests (covers
  FR-004).
- **AC-5**: The shipped example environment file names the option, states
  the default, and describes what it gates (covers FR-005).
- **AC-6**: A provider response that carries no verification signal at all
  is handled the same as an unverified response under the default policy
  (covers FR-006).
- **AC-7**: Automated tests exist for each of AC-1, AC-2, AC-3/AC-4 (both
  policy positions), and AC-6, and they fail without the fix (covers
  FR-007).

## Edge Cases

- Provider sends no verification signal vs. sends an explicit negative: both
  refuse under the default policy.
- Provider sends the signal in a non-boolean shape (e.g. string form):
  only an affirmative verified assertion satisfies the gate.
- An unsigned or provider-independent source repeating the verified claim
  does not satisfy the gate; only the provider assertion on the verified
  sign-in path counts.
- An already-linked external identity signing in again is not affected by
  the auto-link gate (it is a returning sign-in, not a first-connect link).
- Disabled accounts and registration-disabled deployments keep their
  existing refusals; the new refusal does not mask or replace them with a
  distinguishing message.
- Email comparison is case-insensitive; mixed-case variants of the same
  address behave identically.
- Concurrent first-connect attempts for the same email do not create
  duplicate accounts or links.

## Out of Scope

- Proving mailbox control beyond the provider assertion (e.g. a
  confirmation-email round trip before linking); the provider assertion
  remains a provider assertion.
- Per-provider overrides or per-organization SSO restrictions.
- Writing the local email-confirmed state from the provider assertion.
- Session, token, or frontend changes beyond surfacing the existing generic
  failure.
- Database migrations or new endpoints.

## Clarifications

- Q: What is the exact shape and name of the auto-link policy option
  (boolean flag vs. named policy value)? -> A: [NEEDS CLARIFICATION: option
  shape and name — suggested answer: one boolean-style option defaulting to
  verified-email-only.]
- Q: Does an unverified SSO assertion also refuse brand-new account
  provisioning, or only linking to an existing account? -> A: [NEEDS
  CLARIFICATION — suggested answer: refuse both, per AC-1 wording "can
  neither sign in to nor link".]
- Q: Is a missing verification signal treated the same as an explicit
  negative under the default policy? -> A: [NEEDS CLARIFICATION —
  suggested answer: yes, absent means unverified.]
- Q: What exactly is the observable "generic error" (redirect target,
  error string, no token/session)? -> A: [NEEDS CLARIFICATION — suggested
  answer: the existing generic sign-in failure on the callback path, with
  no account-existence signal and nothing issued.]
- Q: Is the pre-hijack refusal keyed on the local account's unverified
  state, the provider assertion, or both? -> A: [NEEDS CLARIFICATION —
  suggested answer: both — an unverified provider assertion never links,
  and a verified provider assertion still does not claim a locally
  unverified password account.]
