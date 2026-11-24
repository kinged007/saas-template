# Checklist: Nonce and browser-bound state cookie for SSO flow (#1864)

- [x] CHK001 Is every AC rejection observable and measurable (302 to the existing `/login?error=` outcome plus unchanged user/session/token state, as asserted by user-count checks)?
- [x] CHK002 Does every acceptance criterion AC-1 through AC-8 appear in at least one task (AC-1: T004/T006; AC-2/AC-3: T001/T005; AC-4/AC-5: T002/T006; AC-6/AC-7: T003/T007; AC-8: T008/T009)?
- [x] CHK003 Does every functional requirement FR-001 through FR-007 trace to an AC and a task with no orphan requirement?
- [x] CHK004 Does the plan avoid inventing a new error surface (reuses `_error_redirect` standard login-error outcome per spec clarification)?
- [x] CHK005 Is the no-ID-token provider case handled (nonce check only when an ID token is returned; cookie check always applies)?
- [x] CHK006 Are cookie flags prescribed without hardcoding (HttpOnly, per-request Secure derivation, SameSite=Lax via `cookies.py`, short-lived, single-use)?
- [x] CHK007 Does the plan introduce no migration, no new dependency, and no frontend change (ephemeral cache entry only)?
- [ ] CHK008 Is the "reference implementation from PR #39" resolved — PR #39 in this repo is closed account-linking work with no nonce implementation, so the plan assumes a fresh implementation; confirm with the project before treating any external reference as normative.
- [x] CHK009 Are the quality-gate commands named with their source (`make api-test` / `make api-lint` from `Makefile`, mirrored in `.github/workflows/ci.yml`)?
- [x] CHK010 Does no task require code outside the confirmed files (`services/oauth.py`, `api/routes/oauth.py`, `core/security/cookies.py` helper-if-needed, `tests/test_oauth.py`)?
