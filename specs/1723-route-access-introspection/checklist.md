# Checklist: Route Access Introspection (#1723)

- [x] CHK001 Is AC-1 measurable? Yes — a test reads the attribute/marker off each of the four gates and compares it to the expected permission string or identity.
- [x] CHK002 Is AC-2 measurable? Yes — `route_access` returns all four fields (permissions, session-only, deployment-admin, workspace) for a route, including one whose gate arrives via a nested dependency.
- [x] CHK003 Is AC-3 measurable? Yes — the test enumerates `app.routes` filtered to `/api/v1` and asserts no error per route, plus three exact spot checks named in the spec.
- [x] CHK004 Is AC-4 measurable? Yes — the existing suite (`make api-test`) passes unmodified; no authorization branch is edited.
- [x] CHK005 Does every FR have a task? FR-001/FR-002 → T002; FR-003/FR-004 → T003; FR-005 → T001 (enumeration) + T003 (unrecognized bucket); FR-006 → T002 (logic untouched) + T004.
- [x] CHK006 Does every task trace to an AC or polish? T001 → AC-3; T002 → AC-1; T003 → AC-2; T004 → AC-4; T005 → polish/smoke + quality gate.
- [x] CHK007 Are spec edge cases covered? Public routes (no requirement, not failure), multi-gate union, optional-workspace conditional, unrecognized-as-unrecognized, non-`/api/v1` routes out of scope, wildcard reported as held — all in plan.md approach/risks and exercised by T001/T003.
- [x] CHK008 Does the plan avoid scope creep? No MCP transport/catalog/pruning/docs work (#1715/#1724–#1727), no schema or doc-output changes, no new dependency — out-of-scope list in plan.md.
- [x] CHK009 Are all named files/functions confirmed? `deps.py` gate line numbers, `main.py` mount prefix, route files and `APIKEY_CREATE = "apikey:create"` verified by grep; `route_access.py` / `test_route_access.py` are explicitly NEW; `apps/api/src/mcp/` confirmed absent by `ls`.
