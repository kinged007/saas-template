# Plan: #1846 Storage foundation with local and in-memory drivers

**Source:** `specs/1846-storage-foundation-drivers/spec.md` (Status: Draft).
No plan-check revise verdict exists; this is a fresh plan.
Area context was missing (no `area:*` label matches, no `.agents/areas/` index —
per triage note); conventions below come from the repo docs and the
secrets/email driver pattern.

## Approach

Mirror the existing env-selected driver pattern exactly:

- `apps/api/src/secrets/base.py` + `factory.py` (`SecretStore` ABC,
  `build_secret_store`, `_SECRET_STORE_DRIVERS` dict, `ValueError` naming
  supported options) and `apps/api/src/email/base.py` + `factory.py` +
  `console.py` (`EmailSender` ABC, `EmailDriver` StrEnum, `build_email_sender`,
  in-memory outbox for tests) are the templates.
- New package `apps/api/src/storage/` with `base.py` (async `StorageAdapter`
  ABC, result dataclasses, typed exceptions, key-validation + content-addressed
  key helpers), `local.py`, `memory.py`, `factory.py` (`StorageDriver` StrEnum
  `local`/`memory`, `build_storage_adapter`, same `ValueError` shape).
- Blocking filesystem work in the local driver runs via `asyncio.to_thread`,
  the same call used in `apps/api/src/email/smtp.py:41`.
- Both drivers issue expiring download URLs through one minimal app-served
  route (new module under `apps/api/src/api/routes/`), so local and the future
  S3 driver share the caller code path; tokens are JWT via the already-installed
  `pyjwt` dependency, keyed by `secret_key`. The in-memory driver serves its
  bytes through the same route (in-process only, for tests).
- The shared contract suite lives next to the other backend tests in
  `apps/api/tests/` (cf. `test_email.py`, `test_secrets.py`) and is written as
  one parametrized module run unchanged against both drivers; pytest already
  runs async tests with `asyncio_mode = "auto"`.

Numeric choices left open by the spec, fixed here within the testable bounds:
max key length 1024, default list page size 100, default signed-URL lifetime
900s (max 86400s; zero/negative rejected), default content type
`application/octet-stream`, stream chunk size 64 KiB.

## Files to change

- `apps/api/src/storage/base.py` (new) — `StorageAdapter` ABC (`put` accepting
  bytes or async byte-stream, returning key/size/content-type/sha256/etag;
  `get`/`open` as async chunk iterators; `head`/`exists`; idempotent `delete`;
  `delete_prefix`; paginated `list` with prefix + cursor; `copy`; `signed_url`
  with expiry + optional download name; `public_url` from configurable base),
  `StoredObject`/`ObjectHead`/`ListPage` dataclasses, `NotFound`/`AccessDenied`/
  `StorageUnavailable` exceptions, `validate_key` (`..` segments, leading `/`,
  length cap) and `content_addressed_key` (`<prefix>/<sha256>.<ext>`) helpers,
  global-prefix application.
- `apps/api/src/storage/local.py` (new) — filesystem driver rooted at
  `STORAGE_DIR`; all blocking I/O in `asyncio.to_thread`; per-key asyncio lock
  so concurrent writes resolve to one complete version; stores sidecar metadata
  (content type, sha256) next to object files.
- `apps/api/src/storage/memory.py` (new) — dict-backed driver with
  `asyncio.Lock`, no filesystem or network use.
- `apps/api/src/storage/factory.py` (new) — `StorageDriver` StrEnum,
  `build_storage_adapter()` reading settings, `ValueError` naming supported
  options for unknown drivers.
- `apps/api/src/settings.py` — add `storage_driver` (default `local`),
  `storage_dir`, `storage_prefix`, `storage_public_base_url`,
  `storage_signed_url_ttl_s`; env names `STORAGE_DRIVER`, `STORAGE_DIR`,
  `STORAGE_PREFIX`, `STORAGE_PUBLIC_BASE_URL`, `STORAGE_SIGNED_URL_TTL_S`.
- `apps/api/.env.example` — document the five new variables (cf. existing
  `SECRET_STORE_DRIVER`/`EMAIL_DRIVER` entries).
- `apps/api/src/api/routes/` new module (e.g. `storage_files.py`) + router
  registration — minimal `GET` download endpoint verifying the JWT bearer
  (expiry + key binding) and streaming bytes with `Content-Disposition`
  honouring the download name; used only by local/memory signed URLs.
- `apps/api/tests/test_storage_contract.py` (new) — shared parametrized
  contract suite (local tmp dir + in-memory) covering every FR: round-trip,
  streaming chunks, head/exists, idempotent delete, prefix delete, paginated
  list, copy/replace, key rejection, typed errors, prefix + content-addressed
  keys, signed-URL expiry/download-name, default content type, empty objects,
  concurrent same-key writes.
- `apps/api/tests/test_storage.py` (new) — factory tests (each `STORAGE_DRIVER`
  value builds the matching driver; unknown value errors naming options) and
  the no-request-context invocation check (plain script, no app/request state).

## Data and contract changes

- Public interface added: `StorageAdapter` and its result/exception types
  (new public surface, no existing callers change). No DB migration, no schema
  change, no existing route or event change, no new dependency (`pyjwt` and
  stdlib `hmac`/`hashlib` cover signing/hashing).
- Config added: five `STORAGE_*` env vars (listed above), all optional with
  documented defaults; `make db-check` unaffected (no models change).

## Test plan (tests first, per AC)

- Contract suite first (`test_storage_contract.py`), parametrized over both
  drivers: AC-1 round-trip (bytes + stream input; size/content-type/sha256/etag
  asserted); AC-2 chunked read/open (assert async-iterator delivery with bounded
  chunk size, reassembled bytes match), head/exists, idempotent delete of a
  never-written key, no-match prefix delete, page size smaller than result set
  (no dup/omission across pages), copy incl. replace and missing-source
  `NotFound`.
- AC-3: event-loop check — concurrent `put`/`get` on the local driver with a
  heartbeat coroutine asserting the loop stays responsive (plus `asyncio.to_thread`
  used for all blocking calls by construction).
- AC-4: `..`, leading `/`, over-length keys rejected on `put` (and read paths);
  missing key → `NotFound`; suite covers `AccessDenied`/`StorageUnavailable`
  mapping points each driver defines.
- AC-5: global prefix test (stored keys carry prefix); helper test (identical
  content + ext → identical `<prefix>/<sha256>.<ext>`; different ext differs).
- AC-6: factory tests per driver value + unknown-value error naming options.
- AC-7: local driver under tmp dir — files visible on disk; signed URL downloads
  bytes before expiry, 4xx after expiry, `Content-Disposition` carries the
  download name; zero/negative lifetime rejected.
- AC-8: full contract suite green on both drivers; context-free invocation test.
- Smoke test: `cd apps/api && uv run python -c "from src.storage.factory import
  build_storage_adapter"` plus `make api-test` subset; API boot via `make api`
  (uvicorn) to prove the new route registers.

## Risks

- Signed-URL route becomes public surface that the follow-up upload-endpoint
  issue (#1849) must reuse, not duplicate — plan names the reuse point.
- Local-driver sidecar metadata layout must stay forward-compatible with the
  `stored_files` table issue; sidecars hold only what the adapter returns.
- `risk:high` label: new public interface + new config + API-served URL path;
  human approves the merge per repo convention.

## Rollback

Revert the new package, route module + registration, settings fields,
`.env.example` entries, and the two test files. No migration to unwind and no
persisted data format outside `STORAGE_DIR` contents, which are disposable
cache-like objects until dependents land.
