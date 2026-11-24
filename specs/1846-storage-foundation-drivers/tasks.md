# Tasks: #1846 Storage foundation with local and in-memory drivers

## Phase 1 — Setup and tests first

- [ ] T001 [AC-1, AC-2] apps/api/tests/test_storage_contract.py — shared parametrized contract suite (round-trip, streaming, head/exists, delete, delete_prefix, paginated list, copy) run against local + in-memory drivers
- [ ] T002 [P] [AC-4] apps/api/tests/test_storage_contract.py — key-validation (`..`, leading `/`, over-length) and typed-error (`NotFound`, `AccessDenied`, `StorageUnavailable`) contract cases
- [ ] T003 [P] [AC-5, AC-7] apps/api/tests/test_storage_contract.py — global-prefix, content-addressed-key, signed-URL expiry/download-name, empty-object, concurrency, default-content-type contract cases
- [ ] T004 [P] [AC-6, AC-8] apps/api/tests/test_storage.py — factory tests (each driver value, unknown-value error) and no-request-context invocation test

## Phase 2 — Implementation

- [ ] T005 [AC-1, AC-2, AC-4, AC-5] apps/api/src/storage/base.py — `StorageAdapter` ABC, result dataclasses, typed exceptions, `validate_key`, `content_addressed_key`, global-prefix helper
- [ ] T006 [AC-1, AC-2, AC-3] apps/api/src/storage/memory.py — dict-backed driver with lock, chunked async iterators, no filesystem/network use
- [ ] T007 [AC-1, AC-2, AC-3, AC-7] apps/api/src/storage/local.py — filesystem driver under `STORAGE_DIR`, blocking I/O in `asyncio.to_thread`, per-key write lock, sidecar metadata
- [ ] T008 [AC-6] apps/api/src/storage/factory.py — `StorageDriver` StrEnum, `build_storage_adapter`, unknown-driver `ValueError` naming options
- [ ] T009 [AC-6, AC-7] apps/api/src/settings.py + apps/api/.env.example — five `STORAGE_*` settings with defaults and documented env entries
- [ ] T010 [AC-7] apps/api/src/api/routes/ new storage download module + router registration — JWT-verified expiring `GET` serving driver bytes with download-name `Content-Disposition`

## Phase 3 — Polish

- [ ] T011 [AC-3] event-loop responsiveness check — heartbeat assertion over concurrent local-driver I/O, proving `asyncio.to_thread` coverage
- [ ] T012 [AC-8] full contract suite green on both drivers — run `make api-test`, fix driver divergences until identical behaviour
- [ ] T013 [polish] smoke test — adapter import + `make api` boot proving route registration, then `make api-lint` (ruff check + format check) clean
