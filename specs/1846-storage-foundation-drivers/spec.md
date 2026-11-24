# Feature Specification: Storage foundation with local and in-memory drivers

**Issue**: #1846  **Status**: Draft  **Areas**: none (area context missing)

## User Scenarios and Testing

### User Story 1 - Application code stores and retrieves objects through one interface (Priority: P1)

A backend developer (or a background job / maintenance script with no
request, user, or workspace context) writes bytes or a stream under a key and
later reads it back, inspects it, copies it, lists it, or deletes it, without
knowing which storage backend is configured. Streaming reads never load the
whole object into memory at once, and blocking filesystem work does not stall
the async event loop.

**Independent test**: with each of the two drivers configured in turn, run a
script with no request context that writes an object, reads it back as a
stream, checks its metadata, copies it, lists it, and deletes it; assert
identical observable behaviour from both drivers.

**Acceptance scenarios**:

1. Given the local driver is configured, When application code writes an
   object and reads it back, Then the bytes, reported size, content type, and
   integrity digests match what was written.
2. Given the in-memory driver is configured, When the same sequence runs,
   Then the observable results are identical to the local driver.
3. Given a large object, When application code reads it as a stream, Then the
   read completes without loading the entire object into memory at once.

### User Story 2 - Operator selects the storage backend through environment (Priority: P1)

An operator deploying the application chooses which storage backend is used by
setting one driver-selection variable, following the same pattern already
used for the secret store and the email sender. Unknown driver names fail
fast with a clear error naming the supported options.

**Independent test**: start the application (or test harness) with each
supported driver value and with an unsupported value; assert the correct
backend is built in each supported case and a descriptive error is raised for
the unsupported value.

**Acceptance scenarios**:

1. Given a supported driver value in the environment, When the storage backend
   is built, Then the matching driver is returned.
2. Given an unsupported driver value, When the storage backend is built, Then
   the build fails with an error that names the supported values.

### User Story 3 - A future driver author proves compatibility with the shared suite (Priority: P2)

The author of a future driver (for example the object-store driver tracked in
the follow-up issue) runs the shared contract test suite that ships with this
work against the new driver and gets a pass/fail signal for every behaviour
in this specification, so driver differences are caught before the upload
endpoints depend on them.

**Independent test**: run the shared contract suite against the local and
in-memory drivers; assert it passes in full on both.

**Acceptance scenarios**:

1. Given the shared contract suite, When it runs against the local driver,
   Then every case passes.
2. Given the shared contract suite, When it runs against the in-memory
   driver, Then every case passes.

## Requirements

- **FR-001**: The system MUST provide one async storage interface usable with
  no request, user, or workspace context, supporting write (bytes or stream,
  reporting key, size, content type, and integrity digests), streaming read,
  streamed open, metadata inspection, existence check, idempotent delete,
  prefix delete, paginated listing, copy, expiring signed download URLs with
  an optional download filename, and a configurable public base URL.
- **FR-002**: Blocking I/O performed by drivers MUST NOT stall the async event
  loop.
- **FR-003**: The system MUST reject unsafe or unusable keys, including keys
  containing parent-directory traversal, keys with a leading separator, and
  keys longer than the documented maximum.
- **FR-004**: The system MUST raise distinct typed errors for missing objects,
  denied access, and unavailable backends.
- **FR-005**: The system MUST support one configurable global key prefix
  applied by the drivers, and MUST provide a helper that derives
  content-addressed keys from content (prefix, content digest, and file
  extension).
- **FR-006**: The system MUST select the storage driver from the environment
  through a single driver-selection variable with a documented default, and
  MUST fail with a descriptive error for unknown driver values.
- **FR-007**: The local-filesystem driver MUST persist objects under a
  configurable directory, and its expiring download URLs MUST be served
  through the application so that callers use the same download code path as
  with presigned remote URLs.
- **FR-008**: The in-memory driver MUST implement the full interface for use
  in unit tests without touching the filesystem or network.
- **FR-009**: The system MUST ship a shared contract test suite that exercises
  every behaviour in this specification and runs unchanged against each
  driver.

## Acceptance Criteria

- **AC-1**: Writing bytes or a stream and reading them back returns identical
  bytes with correct size, content type, and integrity digests on both
  drivers (covers FR-001).
- **AC-2**: Streaming reads and opens deliver content incrementally without
  loading the whole object into memory, and metadata inspection, existence
  checks, idempotent delete (deleting a missing key succeeds), prefix
  delete, paginated listing, and copy all behave identically on both drivers
  (covers FR-001).
- **AC-3**: Load or soak observation shows blocking driver I/O does not stall
  the event loop (covers FR-002).
- **AC-4**: Keys containing parent-directory traversal, keys with a leading
  separator, and keys longer than the documented maximum are rejected; the
  three typed errors (missing object, denied access, unavailable backend)
  are raised in the matching situations (covers FR-003, FR-004).
- **AC-5**: With a global prefix configured, stored keys carry the prefix,
  and the content-addressed helper produces stable keys shaped as
  prefix/digest-plus-extension for identical content (covers FR-005).
- **AC-6**: Setting the driver-selection variable to each supported value
  builds the matching driver, and an unsupported value raises an error naming
  the supported options (covers FR-006).
- **AC-7**: With the local driver configured under a temporary directory,
  objects persist as files there, and an expiring application-served download
  URL for a stored object downloads the object's bytes before expiry, stops
  working after expiry, and honours the requested download filename
  (covers FR-007).
- **AC-8**: The shared contract suite runs unchanged against the local and
  in-memory drivers and passes in full on both, and the interface is invoked
  from a context with no request, user, or workspace present (covers FR-008,
  FR-009, and the context-free part of FR-001).

## Edge Cases

- Empty (zero-byte) objects round-trip with correct size and digests.
- Delete of a key that was never written succeeds (idempotent).
- Prefix delete with a prefix that matches nothing succeeds and removes
  nothing else.
- Listing with a page size smaller than the result set returns all objects
  across pages without duplication or omission.
- Copy onto an existing destination key replaces it; copy of a missing
  source raises the missing-object error.
- Signed URLs requested with zero or negative lifetimes are rejected, and an
  expired URL no longer grants access.
- Concurrent writes to the same key resolve to one complete version (no
  interleaved partial content) on each driver.
- Objects whose content type is not provided get a safe documented default.

## Out of Scope

- The remote object-store driver (follow-up issue) and any cloud credentials,
  buckets, or regions it needs.
- The persistent file-record table and its migration.
- Upload and download HTTP endpoints beyond the minimal application-served
  download path the local driver's signed URLs require.
- Multipart or resumable uploads, lifecycle/retention policies, and
  cross-region replication.
- Public-URL CDN signing beyond a configurable base URL.

## Clarifications

- No open clarification points. The driver-selection pattern, the operation
  set, the exception set, the key-validation rules, and the local-driver
  application-served URL approach are all fixed by the issue description and
  the triage note; numeric choices (exact maximum key length, default page
  size, default URL lifetime) are left to the plan within the testable bounds
  stated above.
