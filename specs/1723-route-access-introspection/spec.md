# Feature Specification: Route Access Introspection

**Issue**: #1723  **Status**: Clarified  **Areas**: none (area context missing — no `.agents/areas/` index in this checkout)

Parent: #1715 (MCP tool discovery and pruning). Related consumers: #1724 (tool catalog builder), #1726 (pruning).

## User Scenarios and Testing

### User Story 1 — Tooling reads every route's gate (Priority: P1)

As the builder of MCP tool discovery and pruning, I need to know for every API route which gate protects it (required permission, session-only, deployment-admin-only, workspace-scoped) so that generated tool listings expose only the operations the caller may use.

**Independent test**: Enumerate all routes served under `/api/v1`, query the introspection for each, and confirm every route yields a well-formed access description without error.

**Acceptance scenarios**:
1. Given the API-key creation route, When its access requirement is queried, Then the result states the `apikey:create` permission is required.
2. Given a self-service account route (e.g. `/me` family), When its access requirement is queried, Then the result states it is session-only.
3. Given a deployment administration route (e.g. admin routes), When its access requirement is queried, Then the result states a deployment admin is required.

### User Story 2 — Authorization behaviour is unchanged (Priority: P1)

As a user of the API, I want every request authorized exactly as before, so that making gates introspectable introduces no privilege widening or narrowing.

**Independent test**: Run the existing backend test suite unchanged and confirm it passes with identical authorization outcomes.

**Acceptance scenarios**:
1. Given any authenticated or unauthenticated request that was previously allowed, When it is replayed after this change, Then it is still allowed with the same result.
2. Given any request that was previously rejected, When it is replayed after this change, Then it is still rejected with the same status.

## Requirements

- **FR-001**: The system MUST expose the permission string held by each permission-based gate in a readable form at runtime.
- **FR-002**: The system MUST make the session-only gate and the deployment-admin gate identifiable at runtime in the same manner as permission-based gates.
- **FR-003**: The system MUST provide a single introspection query that, given one API route, returns its full access requirement: the required permission(s), whether the route is session-only, whether it needs a deployment admin, and whether it needs a workspace (`X-Workspace-ID`).
- **FR-004**: The introspection query MUST derive its answer by walking the route's full dependency tree, so gates applied indirectly (composed or nested dependencies) are included.
- **FR-005**: The introspection query MUST account for every authorization-relevant check on each route under `/api/v1`; a check it does not recognize MUST be surfaced as unrecognized rather than silently reported as no requirement.
- **FR-006**: The change MUST NOT alter any route's authorization outcome.

## Acceptance Criteria

- **AC-1**: Each permission-based gate exposes its permission string in readable form, and the session-only gate and deployment-admin gate are each identifiably distinct through the same mechanism. (covers FR-001, FR-002)
- **AC-2**: A single introspection query accepts a route and returns the required permission(s), session-only flag, deployment-admin flag, and workspace requirement, including gates reached through nested dependencies. (covers FR-003, FR-004)
- **AC-3**: An automated test enumerates every route of the application under `/api/v1` and asserts the query returns a result for each without error; spot checks assert the API-key creation route requires `apikey:create`, self-service account routes are session-only, and admin routes require a deployment admin. (covers FR-003, FR-005)
- **AC-4**: The existing test suite passes unchanged, and no route's authorization result (allowed vs. rejected, and by which gate) differs from before the change. (covers FR-006)

## Edge Cases

- Public routes with no gate (e.g. login/registration): the query returns an access description stating no requirement rather than failing.
- Routes protected by more than one gate: the query reports the union of all requirements found in the dependency tree.
- Routes that read the workspace header optionally (user-scoped for sessions, workspace-scoped for API keys): the query reports the conditional nature instead of a plain required/not-required answer.
- Routes whose access is decided by checks beyond the four named gates (target-scoped or resolving checks): covered by FR-005 — surfaced as unrecognized, never as public.
- Routes outside `/api/v1` (websockets, health probes): outside the enumeration guarantee in AC-3; the query may still describe them but the test does not require it.
- Wildcard (`*`) permissions: reported as the permission value the gate holds, not expanded.

## Out of Scope

- Any change to who is allowed or rejected on any route.
- The MCP transport, endpoint authentication, tool catalog builder, pruning logic, and access documentation (covered by #1715, #1724, #1725, #1726, #1727).
- Changes to the public API schema or documentation output.
- Performance characteristics of the introspection query beyond correctness.

## Clarifications

- None required. The description's AC-1..AC-4 fully determine scope and acceptance; remaining details (representation shape, module placement) are plan-stage decisions that do not change observable behaviour. No `[NEEDS CLARIFICATION]` markers remain.
