# Tasks: #1866 OAuth provider validation + Helm OAUTH_PROVIDERS

## Phase A — Setup and tests first

- [ ] T001 [AC-2] apps/api/tests/test_oauth.py — failing tests: invalid JSON and non-list OAUTH_PROVIDERS → /auth/config advertises nothing, oauth_enabled false, parse failure logged
- [ ] T002 [AC-1, AC-2, AC-4] apps/api/tests/test_oauth.py — failing tests: missing credentials, duplicate ids, issuer-less OIDC entry, non-object entry mixed with valid ones → only valid advertised, each rejection logged without secrets, get_provider still raises for rejected ids, empty config → no SSO and no error log
- [ ] T003 [P] [AC-3] infra/helm/saas-template — capture baseline `helm template` render showing the stale MICROSOFT_*/OKTA_* vars (failing check the fix must invert)

## Phase B — Implementation

- [ ] T004 [AC-1, AC-2, AC-4] apps/api/src/services/oauth.py — validity helper reusing _provider_from/_discovery semantics; get_provider resolves from the valid set
- [ ] T005 [AC-1, AC-2, AC-4] apps/api/src/api/routes/auth.py — auth_config advertises valid providers only; confirm LoginPage/SsoButtons need no change
- [ ] T006 [AC-1, AC-2] apps/api/src/main.py — lifespan logs one entry per rejected provider, never including secrets
- [ ] T007 [P] [AC-3] infra/helm/saas-template/templates/secret.yaml, templates/deployment-api.yaml, values.yaml — render OAUTH_PROVIDERS from one chart value; drop MICROSOFT_*/OKTA_* keys and redirect-uri env; update existingSecret key docs

## Phase C — Polish

- [ ] T008 [polish] smoke test: pytest tests/test_oauth.py + tests/test_oauth_provider.py and `helm template` with/without provider values (AC-3, AC-4 render paths)
- [ ] T009 [polish] quality gate: make api-lint and backend pytest; web untouched so no web-build/web-test beyond CI
