# Checklist: rate-limit failed OAuth callbacks (#1865)

- [x] CHK001 Is AC-1 measurable? Yes — tiny budget + repeated failing callbacks from one address/provider yields HTTP 429; observable in a test without network (monkeypatched provider).
- [x] CHK002 Is AC-2 measurable? Yes — the 429 comes from `SlidingWindowLimiter.check`, which always sets a `Retry-After` header; test asserts the header.
- [x] CHK003 Is AC-3 measurable? Yes — interleave a success (`_mock_oauth` path or 2FA park) between failures and assert the remaining budget is unchanged.
- [x] CHK004 Is AC-4 measurable? Yes — same-budget vs different-address/provider callbacks compared against their own budgets.
- [x] CHK005 Is AC-5 measurable? Yes — read `ratelimit.py` docstring: states failed callbacks consume budget and successes do not.
- [x] CHK006 Is AC-6 measurable? Yes — new/updated tests fail on unmodified code (verified in T005) and pass with the charge present.
- [x] CHK007 Does every FR have a task? FR-001/FR-002 → T002/T006; FR-003 → T003/T006; FR-004 → T004; FR-005 → T007/T008; FR-006 → T001/T009.
- [x] CHK008 Does every AC appear in at least one task? AC-1 → T002/T005/T006; AC-2 → T002/T006; AC-3 → T003; AC-4 → T004; AC-5 → T007/T008; AC-6 → T001/T009.
- [x] CHK009 Does the plan avoid scope creep? Yes — authorize/token endpoints, budget sizes, lockout durations, and limiter storage are out of scope; no new modules or dependencies.
- [x] CHK010 Are all named files/functions confirmed? Yes — `oauth.py` callback + 7 `_error_redirect` sites via grep; `ratelimit.py` docstring lines 6–17 via read; `test_oauth.py` helpers (`_mock_oauth`, `_callback`) and `test_oauth_callback_account_gone_redirects` via read; `make api-test`/`make api-lint` from `Makefile`.
- [x] CHK011 Does the plan handle the known old-behavior lock-in? Yes — T001 updates `test_oauth_callback_account_gone_redirects`, which currently asserts no 429 with budget of 1.
- [x] CHK012 Is the 2FA-park edge case covered? Yes — spec clarifies the park is a success; T003 covers it and T006 leaves that return uncharged.
