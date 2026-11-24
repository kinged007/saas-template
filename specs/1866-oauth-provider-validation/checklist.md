# Checklist: #1866 plan and spec quality

- [x] CHK001 AC-1 is measurable: a mixed valid/invalid config must advertise only the valid provider and the startup log must name the rejected id and reason (T002 asserts both).
- [x] CHK002 AC-2 covers every defect class with its own test: invalid JSON, non-list JSON, missing credentials, duplicate ids, issuer-less OIDC entry, non-object entry (T001, T002).
- [x] CHK003 AC-3 covers both Helm secret paths: chart-managed secret renders OAUTH_PROVIDERS and a user-supplied existingSecret is documented to carry the OAUTH_PROVIDERS key (T007 updates the values.yaml key docs).
- [x] CHK004 AC-4 distinguishes empty/unset config (valid-but-empty, no SSO, not an error log) from malformed config (logged failure); both asserted (T002).
- [x] CHK005 Every FR-001..FR-009 maps to at least one task: FR-001/002/004/005 via T002+T004+T006; FR-003 via T001+T004; FR-006 via T004+T005; FR-007 via T005; FR-008/009 via T007.
- [x] CHK006 The validity predicate is pinned to _discovery/_provider_from semantics (OIDC path via discovery_url or issuer, else explicit authorize+token URLs), so no login-capable provider is rejected and no advertised provider is doomed at discovery (T004; risk noted in plan).
- [x] CHK007 Rejection logs provably exclude secrets: tests grep captured log text for the secret value (T002).
- [x] CHK008 Duplicate-id precedence is decided and recorded: first valid occurrence kept, later repeats rejected and logged (spec assumption carried into T002/T004).
- [x] CHK009 The Helm values-shape question is decided: one chart value carrying the provider list, rendered verbatim as OAUTH_PROVIDERS JSON via toJson; per-vendor keys removed (T003 baseline exists so the shape choice is reviewable, T007 implements).
- [x] CHK010 Quality-gate commands are named with their source: make api-lint plus pytest from Makefile targets and .github/workflows/ci.yml; helm template as the AC-3 render check; web jobs not rerun locally because no web file changes (T008, T009).
- [x] CHK011 No web change is justified by read evidence: LoginPage guards ssoProviders.length, SsoButtons returns null on empty, fetchAuthConfig defaults to empty (verified in T005).
- [x] CHK012 Every file and function named above was confirmed with ls/grep/read during planning; no task invents a file, function, or harness.
