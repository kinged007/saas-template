# Checklist: MCP tool catalog from FastAPI routes (#1724)

- [x] CHK001 Is AC-1 measurable? Yes: tool count equals eligible APIRoute count, each tool has name/description/valid schema (T002 asserts it).
- [x] CHK002 Does every AC appear in a task? AC-1 → T002/T003/T005; AC-2 → T003; AC-3 → T002/T004; AC-4 → T001.
- [x] CHK003 Does every FR have a task? FR-001/FR-006 → T003; FR-002/FR-003 → T003; FR-004/FR-005 → T003 (+T001 proves); FR-007 → T004 (+T002 proves); FR-008 (purity) holds by construction — sync function of the app, no I/O/auth, unit-tested without DB.
- [x] CHK004 Is the parameter-clash rule deterministic with no silent loss? Yes: path > query > body precedence, documented in plan.md; path/query same-name params are already one FastAPI argument.
- [x] CHK005 Does the exclusion approach need no per-router work? Yes: default-include; one static list plus `x-mcp-exclude` opt-out (T004/T001).
- [x] CHK006 Do tests avoid heavy fixtures? Yes: AC-4 tests use a minimal in-test app (no DB/lifespan); full-app tests reuse the existing conftest.
- [x] CHK007 Are named files/functions grounded? Yes: all paths confirmed via ls/grep (`src/main.py`, `src/api/routes/*`, `src/api/deps.py`, `tests/`); only the two new files are proposed, in confirmed directories.
- [x] CHK008 Is rollback safe? Yes: two new files only, no migration/config/existing-code changes.
- [x] CHK009 Is a smoke test defined? Yes: targeted pytest run of the new module (T006).
