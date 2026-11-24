# Plan: Validate OAuth providers, advertise only valid ones; wire Helm OAUTH_PROVIDERS (#1866)

Source: `spec.md` in this directory (Status: Clarified) plus the spec-stage
summary comment on the issue. No `plan-check` revise verdict exists (round 1),
so this plan is written fresh from the spec. Area context was missing: this
repo has no `.agents/areas/` index, so code locations below were confirmed by
direct `grep`/`read` during planning.

## Approach

One validity pass over `OAUTH_PROVIDERS`, applied everywhere the raw list is
read today. The pass lives next to the code that already interprets provider
entries (`apps/api/src/services/oauth.py`, beside `_provider_from` and
`get_provider`) so validation can never drift from what a login would accept:

- New helper parses `settings.oauth_provider_list` once and returns the valid
  `ProviderConfig` list plus one `(entry-ref, reason)` rejection per invalid
  entry. An entry is valid only if: it is an object with a non-empty string
  `id`; `client_id` and `client_secret` are present; the id is not a repeat
  of an already-accepted id (first valid wins, later repeats rejected); and it
  is endpoint-usable under the same rule `_discovery` uses — OIDC path via
  `discovery_url` or `issuer`, otherwise explicit `authorize_url` + `token_url`
  (the GitHub-style non-OIDC path). Unset/empty config stays valid-but-empty.
- Startup (`lifespan` in `apps/api/src/main.py`, next to the existing
  `untrusted_emails_urls` report) logs one line per rejected entry stating the
  reason. Rejection lines never contain secret values. The service still
  starts; invalid JSON / non-list input logs the parse failure and advertises
  nothing.
- `GET /auth/config` (`apps/api/src/api/routes/auth.py:133-148`) builds
  `providers` and `oauth_enabled` from the valid list only. Response shape is
  unchanged. `get_provider` resolves from the same valid set, so a rejected
  provider requested directly still raises `OAuthError` instead of succeeding.
- Web: no change. `LoginPage` renders `SsoButtons` only when
  `ssoProviders.length > 0`, `SsoButtons` returns null on an empty list, and
  `fetchAuthConfig` defaults to an empty provider list — filtering in
  `/auth/config` is sufficient for AC-1/AC-4.
- Helm: replace the per-vendor `api.oauth` keys in
  `infra/helm/saas-template/values.yaml` with one value carrying the provider
  list, rendered via `toJson` as `OAUTH_PROVIDERS` in `templates/secret.yaml`;
  delete the unread `MICROSOFT_*`/`OKTA_*` keys there and the
  `MICROSOFT_REDIRECT_URI`/`OKTA_REDIRECT_URI` env entries in
  `templates/deployment-api.yaml` (confirmed: nothing else references them,
  the API never reads them). Document that a user-supplied `existingSecret`
  must carry the `OAUTH_PROVIDERS` key.

Assumptions carried from the spec's non-blocking questions (treated as
answered with the suggestion): duplicate ids keep the first valid occurrence;
the chart takes the provider list as a single value rendered verbatim as
`OAUTH_PROVIDERS` JSON.

## Files to change

- `apps/api/src/services/oauth.py` — add the validity helper; make
  `get_provider` resolve from the valid set (existing credential check stays
  as the last line of defence).
- `apps/api/src/api/routes/auth.py` — `auth_config` advertises valid
  providers only; `oauth_enabled` reflects the valid list.
- `apps/api/src/main.py` — `lifespan` logs one entry per rejected provider
  (no secrets), beside the existing emails-url report.
- `apps/api/tests/test_oauth.py` — failing-first tests per AC (monkeypatch
  `settings.oauth_providers`, `caplog` for reasons, `app_client` GET
  `/auth/config` as in `test_config_reflects_flags`).
- `infra/helm/saas-template/values.yaml` — single provider-list value
  replacing `api.oauth` per-vendor keys; updated `existingSecret` key docs.
- `infra/helm/saas-template/templates/secret.yaml` — render `OAUTH_PROVIDERS`;
  remove `MICROSOFT_*`/`OKTA_*`.
- `infra/helm/saas-template/templates/deployment-api.yaml` — remove the two
  unread redirect-uri env entries.

Explicitly unchanged: `apps/web/src/components/AuthConfig.tsx`,
`apps/web/src/pages/LoginPage.tsx` (already empty-safe, verified by read);
`settings.oauth_provider_list` raw-parse behaviour (the helper layers on top);
OAuth login/callback/token flow; DB models (no migration).

## Data and contract changes

- `GET /auth/config`: same keys, filtered content — `providers` holds only
  valid `{id, display_name}`, `oauth_enabled` is false when none is valid.
  No secrets leave the server (unchanged).
- Helm values: breaking rename of `api.oauth.*` per-vendor keys to one
  provider-list value. Real-world impact is nil — the old keys produced env
  vars the API never read, so no working SSO can depend on them — but the
  rename is called out in the PR.
- New startup log lines (one per rejection, secrets excluded). No new env
  vars, no dependency, no migration, no persisted-data change.

## Test plan

Tests first, one per defect class, all in `apps/api/tests/test_oauth.py`
(follows the existing `monkeypatch.setattr(settings, "oauth_providers", ...)`
+ `app_client` pattern):

1. AC-1: valid + missing-secret providers → config lists only the valid one;
   startup log names the rejected id and reason.
2. AC-2a: invalid JSON and non-list JSON → no providers advertised,
   `oauth_enabled` false, parse failure logged.
3. AC-2b: duplicate ids → id advertised at most once (first valid kept),
   repeat logged.
4. AC-2c: issuer-less OIDC-style entry and non-object entries → excluded and
   logged; direct `get_provider` on a rejected id still raises.
5. AC-4: empty/unset config → `oauth_enabled` false, `providers` [], and this
   is not logged as an error.
6. AC-3: `helm template` with provider values set renders `OAUTH_PROVIDERS`
   and no `MICROSOFT_*`/`OKTA_*`; render with values unset stays deployable.
   Rejection-log assertions also grep the captured text for the secret value
   to prove it is never logged.

Smoke test (smallest real run the repo documents): `cd apps/api &&
uv run --extra dev pytest tests/test_oauth.py tests/test_oauth_provider.py`
plus `helm template ./infra/helm/saas-template` with provider values set.
Quality gate: `make api-lint` (`ruff check` + `ruff format --check`) and the
same pytest run; web is untouched so no `web-build`/`web-test` needed beyond
CI. Commands from `Makefile` targets and `.github/workflows/ci.yml`.

## Risks

- Predicate stricter than login reality hides a working provider. Mitigated by
  deriving endpoint-usability from `_discovery` semantics and testing a
  GitHub-style explicit-endpoint provider as valid.
- Predicate looser than login reality advertises a doomed button. Mitigated by
  keeping `get_provider`'s credential check and letting direct requests fail.
- Helm values rename surprises chart users. Old keys were unread, so nothing
  working breaks; still flagged in the PR body.
- Startup-log volume: one line per rejected entry is bounded by config size;
  no per-request logging is added.

## Rollback

Revert the commit(s). No migration, no data change, no new env var: the API
falls back to advertising the raw list and the chart to per-vendor keys.
Chart users who already switched to the new values key switch back with it.
