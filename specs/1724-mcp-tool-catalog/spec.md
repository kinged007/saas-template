# Feature Specification: MCP tool catalog from FastAPI routes

**Issue**: #1724  **Status**: Clarified  **Areas**: none (no area context exists for the API backend)

## User Scenarios and Testing

### User Story 1 - Agent discovers every API operation as a tool (Priority: P1)

An AI agent connected over MCP asks for the tool list and sees one tool per
API endpoint, each with a unique stable name, a human-readable description,
and a JSON input schema, so the agent knows what it can do without any
hand-maintained tool registry.
**Independent test**: build the catalog from the application and check that
the number of tools equals the number of eligible routes, and that every tool
has a name, a description and a valid JSON Schema.
**Acceptance scenarios**:
1. Given the full application, When the catalog is built, Then there is exactly one tool per eligible route under `/api/v1` and no tool for any other route.

### User Story 2 - Agent call maps cleanly onto the HTTP route (Priority: P1)

An MCP server receiving a tool call needs the HTTP method and the path
template plus the caller's arguments to reach the real endpoint, so each tool
definition carries everything required for dispatch.
**Independent test**: for a sample of tools spanning path, query and body
parameters, check the recorded method and path template match the route and
the arguments fill every placeholder.
**Acceptance scenarios**:
1. Given any tool in the catalog, When its dispatch record is read, Then it names the exact HTTP method and path template of its route.

### User Story 3 - Sensitive and non-agent routes stay hidden (Priority: P2)

A user does not want an agent to see credential-handling or connection
endpoints (login, registration, token refresh, logout, password reset,
OAuth callbacks, two-factor setup, WebSocket channels, the MCP endpoint
itself), so those routes never appear as tools.
**Independent test**: build the catalog and check none of the excluded routes
is present, while ordinary resource routes still are.
**Acceptance scenarios**:
1. Given the full application, When the catalog is built, Then no credential, OAuth-callback, two-factor-setup, WebSocket or MCP-transport route appears as a tool.

### User Story 4 - New endpoints appear with no extra work (Priority: P1)

A developer adding a new router gets MCP coverage for free and can opt a
single route out without touching shared configuration, so the catalog stays
complete as the API grows.
**Independent test**: mount an extra test router on a test application and
check its routes appear as tools; mark one route to opt out and check it does
not appear.
**Acceptance scenarios**:
1. Given a test application with an added router, When the catalog is built, Then the new routes appear as tools without any catalog change.
2. Given a route marked with the per-route opt-out marker, When the catalog is built, Then that route does not appear.

## Requirements

- **FR-001**: The builder MUST return one tool definition per eligible route
  under `/api/v1`.
- **FR-002**: Each tool MUST have a name that is stable across restarts and
  unique within the catalog, derived from the route's operation identifier
  when one is set and otherwise from the HTTP method plus the path.
- **FR-003**: Each tool MUST carry a human-readable description taken from
  the route's summary first, falling back to longer route documentation and
  then to the handler docstring when the summary is absent.
- **FR-004**: Each tool MUST carry an `inputSchema` that combines the route's
  path parameters, query parameters and JSON request body into a single JSON
  Schema object.
- **FR-005**: Every `$ref` inside an `inputSchema` MUST be resolved against
  the application's generated schema components, so the schema is
  self-contained and needs no follow-up fetch to interpret.
- **FR-006**: Each tool MUST record the HTTP method and the path template
  needed to dispatch a call to its route.
- **FR-007**: The builder MUST exclude routes that make no sense for an
  agent (credential handling, OAuth callbacks, two-factor setup, WebSocket
  routes and the MCP endpoint itself) using one explicit exclusion list plus
  a per-route opt-out marker; every route not excluded MUST be included by
  default.
- **FR-008**: The builder MUST be pure: it performs no network transport and
  no authentication or authorization itself.

## Acceptance Criteria

- **AC-1**: Building from the application yields one tool per eligible
  `APIRoute` under `/api/v1`, each with a stable unique name, a description,
  and an `inputSchema` combining path, query and body parameters with all
  `$ref`s resolved. (covers FR-001, FR-002, FR-003, FR-004, FR-005)
- **AC-2**: Each tool records the HTTP method and path template needed to
  dispatch it. (covers FR-006)
- **AC-3**: Credential, OAuth-callback, two-factor-setup, WebSocket and MCP
  routes are absent from the catalog; exclusion comes from one explicit list
  plus the per-route opt-out marker, and a newly added router is included
  with no extra work. (covers FR-007)
- **AC-4**: A test suite proves that adding a test router to a test
  application surfaces its routes as tools without other changes, that an
  opted-out route does not appear, and that a route with path, query and body
  parameters produces the expected `inputSchema`. (covers FR-001, FR-004,
  FR-007)

## Edge Cases

- Two routes that would produce the same tool name (for example identical
  handler names or the same method plus path shape) still yield unique names.
- A route with no parameters produces an `inputSchema` that accepts an empty
  object rather than failing or demanding properties.
- A request body schema that references itself (directly or through a cycle)
  resolves to a finite schema without infinite expansion.
- The same path served under several HTTP methods yields one tool per
  method, each with the correct method recorded.
- Routes that share a parameter name between the path and the query keep both
  meanings without one silently overwriting the other.
- Non-`APIRoute` entries (mounted sub-applications, static handlers) are
  skipped rather than crashing the build.

## Out of Scope

- The MCP network transport and endpoint mounting (parent #1715, child #1725).
- Authentication, credential forwarding and permission-based pruning of the
  tool list (children #1723, #1726).
- A setting to enable or disable the MCP feature.
- SDK dependencies, packaging or lockfile changes.
- End-user documentation for MCP usage (child #1727).

## Clarifications

- Q: When a route has no explicit operation identifier, how is the stable
  tool name derived? -> A: Slug of lowercase HTTP method plus the path
  template (chosen by agent; explicit identifiers take precedence when set).
- Q: What is the description fallback order when a route summary is absent?
  -> A: Route summary, then longer route documentation, then handler
  docstring, then a generated placeholder naming the method and path
  (chosen by agent).
- Q: How is the per-route opt-out expressed? -> A: A flag in the route's
  extra OpenAPI metadata (chosen by agent; matches the form suggested in
  the issue).
- Q: On a parameter-name clash between path/query/body in the merged
  `inputSchema`, which wins? -> A: The plan stage defines one deterministic
  rule and documents it; no silent data loss is acceptable (chosen by
  agent).
