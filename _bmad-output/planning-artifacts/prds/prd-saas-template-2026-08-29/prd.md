---
title: Extendable User Profiles
created: 2026-08-29
updated: 2026-08-29
status: final
---

# PRD: Extendable User Profiles
*Template-repo feature — a separate, easily-extendable profile layer on top of the existing `users` table.*

## 0. Document Purpose

This PRD is for the Product Manager, Architect, and downstream Build agents that will implement the feature inside `apps/api` (FastAPI + SQLAlchemy) and `apps/web` (Refine.dev v5 + shadcn/ui). It builds on the existing domain model documented in `docs/ARCHITECTURE.md` (`User`, `Workspace`, `WorkspaceMember`, `Role`) and the current auth surface (`apps/api/src/api/routes/auth.py:1`, `apps/api/src/services/auth.py:1`, `apps/web/src/types.ts:13`). Glossary (`§3`) anchors all vocabulary; Features (`§4`) group behavior with globally-numbered FRs; all `[ASSUMPTION]` tags are indexed in `§9`. Implementation details (SQL dialect quirks, migration tooling, exact helper signatures) belong in `addendum.md` — this PRD specifies *what*, not *how*.

## 1. Vision

Every SaaS product needs richer user identity than `email + display_name + avatar_url` (`apps/api/src/models/workspace.py:11`), but no two products need the *same* richness. A template repo must therefore ship a profile abstraction that satisfies the 80% case out of the box, stores the long tail without a schema migration, and makes it trivial for a forking team to promote a JSON key to a first-class column later.

This feature introduces a dedicated **UserProfile** model, 1:1 with `User` (`user_id` unique FK), containing curated common profile fields and a schemaless `custom_data` JSON bag. Backend Pydantic schemas and frontend TypeScript types expose the same dual-layer contract: callers can read/write any declared field *or* any key inside `custom_data` through a uniform accessor, without foreknowledge of what a future fork will add. `GET /auth/me` (`apps/api/src/api/routes/auth.py:93`) embeds the profile (see FR-5); `GET /me/profile` remains as the focused profile endpoint and both are lazily auto-created on first access. The product also gains the minimal GDPR-grade lifecycle endpoints a user expects: `GET /me/export` (user + profile + memberships + tokens redacted) and `DELETE /me` (self-service account deletion with cascade).

The result is a template primitive that feels like a real product feature on day one, and remains boring to extend on day 500. Forks keep one migration and two type files as their extension seam — not a rewrite. Future `Agent` entities (planned) are intentionally out of scope: agents will own an `AgentProfile` table of their own and do not share this seam.

## 2. Target User

### 2.1 Jobs To Be Done

- **As a template builder / product engineer**, I can add a new profile attribute (e.g., `job_title` or `department`) in one backend model change + one frontend type change and fetch it from any UI or API without touching generic helpers — so extending identity doesn't require forking the data-access layer.
- **As an end-user**, I can view and edit my own profile (name parts, bio, phone, timezone, etc.) and persist ad-hoc preferences inside `custom_data` — so my identity reflects how *this* product sees me, beyond what `users.display_name` captures.
- **As an end-user**, I can export my data and delete my own account without opening a support ticket — so data-portability and erasure requirements are met from day one.
- **As a workspace admin / teammate**, I can read other members' public profile fields when we share a workspace — so member directories, chat participants, and mentions have consistent display context. I cannot enumerate users outside my workspaces.
- **As a backend or frontend API consumer**, I can fetch any field — whether it was declared as a column or stored as a JSON key — through the same accessor and display it without a code change — so UI assembled from external configuration or workspace-defined custom attributes still renders.
- **As an operator**, I can audit profile changes and reason about PII handling (GDPR erase/export) without bespoke tooling — so compliance inherits the existing audit-log and user-lifecycle contracts.

### 2.2 Non-Users (v1)

- Anonymous visitors (no profile before account creation).
- Service accounts / `ApiKey` principals — profiles belong only to human `User` rows. [RESOLVED: `Agent` entities are a separate product concept and will own `AgentProfile` (`agents` / `agent_profiles`) — explicitly not part of this PRD and must not be conflated with `UserProfile`]
- Cross-workspace directory consumers expecting org-wide search; v1 lookup is bounded by workspace membership or self-access only.

### 2.3 Key User Journeys

- **UJ-1. Amara creates an account and lands with a usable profile.**
  - **Persona + context:** Amara, solo founder bootstrapping on the template, registers via `POST /auth/register` on web.
  - **Entry state:** Unauthenticated, on `/register`. Submits `email`, `display_name`, `password`.
  - **Path:** API creates `User` then auto-provisions linked `UserProfile` (defaults only, `avatar_url` remains `null` on `users` until set; upload deferred); returns tokens; web fetches `GET /auth/me` (now with embedded `profile`) and renders profile preview without a second round-trip. Amara sees display name pre-filled from registration.
  - **Climax:** Profile exists without manual step; zero 404s; identity payload already contains profile.
  - **Resolution:** Amara navigates to `/settings/profile` to complete remaining fields.
  - **Edge case:** If profile row race occurs (concurrent login before provisioning), `get_or_create` is idempotent — second call returns existing row. Realizes FR-1, FR-6, FR-10.

- **UJ-2. Amara edits her own profile in Settings.**
  - **Persona + context:** Authenticated, on `/settings/profile` (new route).
  - **Entry state:** JWT with `sub`, workspace context optional.
  - **Path:** Page loads via `GET /me/profile` (or from the embedded profile in `GET /auth/me`); form bound with `useForm` + `zodResolver`; edits `first_name`, `bio`, `timezone`; saves via `PATCH /me/profile` with payload `{ first_name: "Amara", custom_data: { twitter_handle: "@amara_builds" } }` following JSON Merge Patch semantics.
  - **Climax:** Toast confirms success; helper `getProfileField(profile, "twitter_handle")` immediately reflects new value elsewhere (header avatar menu, member list).
  - **Resolution:** Updated values appear on next `GET /auth/me` (embedded) or any component reading profile context. Realizes FR-4, FR-5, FR-9, FR-11, FR-12.

- **UJ-3. Ben looks up a teammate's profile inside a workspace.**
  - **Persona + context:** Ben, editor in workspace `acme`, views Members page.
  - **Entry state:** Authenticated, `X-Workspace-ID: acme` header set.
  - **Path:** Members list fetches `GET /workspaces/acme/members` (existing); clicking a member fetches `GET /users/{userId}/profile` scoped to membership check.
  - **Climax:** Directory shows `first_name + last_name`, `bio` snippet, and any non-private custom keys the template exposes (e.g., `department`). `avatar_url` is read from `users.avatar_url` (still `null`/empty until the user sets a URL — no upload in v1).
  - **Resolution:** Ben can mention or message with correct display context. **Edge case:** if requester and target share no workspace and target is not self, API returns 404 (no enumeration). Realizes FR-3, FR-7.

- **UJ-4. Fork team extends the template with a new field.**
  - **Persona + context:** Priya, engineer forking the template for a recruiting product, needs `years_of_experience`.
  - **Entry state:** Local clone, prior PRD/Architecture implemented.
  - **Path:** Adds column `years_of_experience INT NULL` to model `apps/api/src/models/profile.py`, extends Pydantic schemas (`ProfileRead`/`ProfileUpdate`) and Alembic migration; extends `apps/web/src/types.ts` `UserProfile` type and, optionally, promotes `custom_data.years_of_experience` values via one-off script; no changes to generic `getProfileField` or dataProvider.
  - **Climax:** `GET /me/profile` (and embedded `GET /auth/me`) returns `years_of_experience: 5` as top-level field; `getProfileField(profile, "years_of_experience")` still works even before UI adds a dedicated input.
  - **Resolution:** New field is queryable and editable at the same endpoints; existing clients tolerate unknown keys. Realizes FR-9, FR-13.

- **UJ-5. Amara exports and then deletes her account.**
  - **Persona + context:** Amara invokes data-portability/erasure.
  - **Entry state:** Authenticated.
  - **Path:** `GET /me/export` returns a timestamped JSON bundle: `user`, `profile`, `workspaces` (memberships + roles), `audit_entries` (own actions), excluding secrets; `DELETE /me` with password confirmation (or `confirm: "DELETE"` for OAuth users) hard-deletes `users` (cascades to `user_profiles`, `refresh_tokens`, `workspace_members`, etc.), revokes tokens, and publishes `user.deleted`.
  - **Climax:** Export downloads; delete returns 204 and subsequent `GET /auth/me` is 401.
  - **Resolution:** Audit retains `user.deleted` but no PII payload; workspace memberships left empty are visible to remaining owners. Realizes FR-14, FR-15, FR-16.

## 3. Glossary

- **User** — Existing `users` row (`apps/api/src/models/workspace.py:11`): `id`, `email`, `password_hash`, `display_name`, `avatar_url` (nullable, empty by default; URL string, no upload in v1), `is_active`, `is_superuser`. Identity root; extended attributes live on `UserProfile`.
- **UserProfile** — New `user_profiles` row (this PRD). 1:1 with User via `user_id` UNIQUE FK (`ON DELETE CASCADE`). Holds common fields + `custom_data` JSON bag. Extends, does not replace, User. [RESOLVED: not to be reused for future `Agent` entity — agents get `AgentProfile`]
- **Agent / AgentProfile** — Planned separate entity (not this PRD). Will be modeled as `agents` / `agent_profiles` with its own lifecycle. Mentioned here only to avoid conflation; no implementation, no shared seam.
- **Common Fields** — Declared columns on `UserProfile`: `first_name`, `last_name`, `bio`, `phone_number`, `timezone`, `locale`, `date_of_birth`, `website_url`, `location`. [RESOLVED: v1 set approved]. Timestamps `created_at`, `updated_at` via `TimestampMixin` (`apps/api/src/db/base.py:50`).
- **Custom Data** — Schemaless JSON object `custom_data` (JSONB on Postgres, TEXT JSON on SQLite via existing `StringUUID` pattern) stored on `UserProfile`. Default `{}`. Holds arbitrary product-specific keys without schema change. Mutated via JSON Merge Patch (RFC 7396) semantics: shallow merge, `null` deletes a key. Bounded (see FR-3).
- **Accessor** — Uniform read helper `getProfileField(profile, key, fallback?)` that resolves `key` as top-level column if present, else inside `custom_data`. Backend equivalent: serializer merges top-level + `custom_data` projection when requested.
- **Extension Seam** — The two-file contract where a fork adds a first-class field: backend model + schema (`apps/api/src/models/profile.py`, `apps/api/src/schemas/api.py`) and frontend type (`apps/web/src/types.ts`). Generic helpers need not change.
- **Own Profile** — Profile where `UserProfile.user_id == auth.sub`. Updatable/exportable/deletable by its owner.
- **Public Profile** — Read-only projection of another user's profile visible to workspace co-members only (see FR-6). Excludes private keys. [RESOLVED: co-membership is the sole read gate]
- **Workspace Membership** — Existing `WorkspaceMember` (`apps/api/src/models/workspace.py:67`) binding `user_id ↔ workspace_id ↔ role_id`. Gates cross-user profile reads.
- **Profile Service** — Backend domain service `src/services/profiles.py` (new) handling `get_or_create`, `update`, `export`, and authorization.

## 4. Features

### 4.1 Profile Model & Lifecycle

**Description:** A separate `user_profiles` table, 1:1 with `users`. Provisioned automatically on user registration (`AuthService.register`, `AuthService.upsert_oauth_user`), backfilled for existing users via migration/seed, and lazily `get_or_create`-d on first `GET /me/profile` or `GET /auth/me` to handle races or direct DB inserts. Deleting a `User` cascades to profile. Follows existing `Base` + `TimestampMixin` conventions and the `StringUUID`/`JSON` patterns already used in `Role.permissions` (`apps/api/src/models/workspace.py:63`). Realizes UJ-1, UJ-4.

**Functional Requirements:**

#### FR-1: Auto-provisioned 1:1 profile row

System creates a `UserProfile` linked to every `User` at registration time (password or OAuth) and backfills existing `users` without a profile on migration. `GET /me/profile` and `GET /auth/me` are both idempotent: if no row exists, they create one and return it.

**Consequences (testable):**
- `POST /auth/register` results in a `user_profiles` row with `user_id == new user.id` within the same transaction (or immediate follow-on committed before token issuance).
- Starting from a DB with N legacy users, running migrations leaves exactly N profiles (one per user).
- Concurrent `GET /me/profile` calls for the same new user yield 200 with identical `user_id` and do not raise unique-violation to the caller (retry/idempotent).
- `GET /auth/me` for a legacy user without a profile backfills lazily and returns `profile` embedded, with `custom_data: {}`.

#### FR-2: Common profile columns

`UserProfile` exposes: `first_name` (varchar 100, nullable), `last_name` (varchar 100, nullable), `bio` (varchar 1000 / text, nullable), `phone_number` (varchar 30, nullable), `timezone` (varchar 50, nullable), `locale` (varchar 10, nullable), `date_of_birth` (date, nullable), `website_url` (varchar 500, nullable), `location` (varchar 200, nullable), plus `created_at`/`updated_at`. `avatar_url` remains on `User` (`String(500)`, nullable) and defaults to `null`/empty string; no upload, no avatar handling in this PRD. [RESOLVED: set approved; avatar stays on `users`]

**Consequences:**
- Alembic migration creates `user_profiles` with listed columns, `user_id UUID UNIQUE REFERENCES users(id) ON DELETE CASCADE`, `custom_data JSON NOT NULL DEFAULT '{}'`.
- `GET /me/profile` for a fresh user returns all common fields as `null` (or omitted) and `custom_data: {}`.
- Attempt to store `bio` >1000 chars is rejected with 422.

**Out of Scope:**
- Avatar file upload, resizing, or storage; the field holds a URL string that the user pastes (may be `null`/empty).

### 4.2 Schemaless Metadata

**Description:** A `custom_data` JSON bag holds arbitrary keys. Callers mutate it via JSON Merge Patch (RFC 7396) — a professional, widely-understood contract that is trivial for both backend and frontend to implement: `PATCH` shallow-merges `custom_data`; a key set to `null` deletes it; omitted keys are retained. Size is bounded; keys are namespaced by convention. Accessor resolves both layers uniformly. Enables template forks to capture product-specific attributes without a migration, and to later promote hot keys to columns. Realizes UJ-2, UJ-4.

**Functional Requirements:**

#### FR-3: Bounded JSON bag with Merge Patch semantics

`custom_data` is `dict[str, Any]` constrained to JSON-serializable primitives/objects, max serialized size 16 KiB per profile [ASSUMPTION: tunable via settings], max 50 top-level keys [ASSUMPTION]. Persisted as `JSON/JSONB`. Empty bag defaults to `{}`. `PATCH /me/profile` treats `custom_data` as a JSON Merge Patch object: shallow-merge top-level keys, `null` removes a key, omission preserves it. Full replacement uses `PUT /me/profile` with an explicit `custom_data` object. Validated for size after merge.

**Consequences:**
- `PATCH /me/profile` with `{ custom_data: { twitter_handle: "@x" } }` after previous `{ keep: 1 }` yields `{ keep: 1, twitter_handle: "@x" }`.
- `PATCH /me/profile` with `{ custom_data: { keep: null } }` deletes `keep`, yielding `{ twitter_handle: "@x" }`.
- `PUT /me/profile` with `{ first_name: "A", custom_data: { only: 1 } }` replaces the bag exactly with `{ only: 1 }`.
- Payload that would exceed 16 KiB after merge returns 422 with `detail` naming the limit.
- Stored value round-trips exactly.

#### FR-4: Uniform accessor (read path)

Both backend and frontend provide a single helper that resolves any field name regardless of storage layer: (a) if key matches a declared `UserProfile` column or `User` public field, return column value; (b) else return `custom_data[key]`; (c) else fallback/default. Backend serializer supports optional flattening projection; frontend exports `getProfileField` from `src/types.ts` (or `src/lib/profile.ts`) with the same semantics. [ASSUMPTION: frontend helper lives beside types for import ease].

**Consequences:**
- `getProfileField(profile, "first_name")` returns top-level column value.
- `getProfileField(profile, "twitter_handle")` returns `profile.custom_data.twitter_handle` when `first_name` lookup misses.
- `getProfileField(profile, "nonexistent", "N/A")` returns `"N/A"`.
- New columns added via the extension seam are automatically reachable through the same call (top-level-first).

### 4.3 Profile API Surface

**Description:** Minimal REST surface, authenticated via existing JWT (`get_current_user`), workspace-aware for cross-user reads. Uses existing `X-Workspace-ID` pattern where relevant. Pydantic schemas follow `apps/api/src/schemas/api.py:1` style. `GET /auth/me` always embeds the profile (lazy-created). Realizes UJ-2, UJ-3, UJ-5.

**Functional Requirements:**

#### FR-5: Own-profile read/write + embedded identity

- `GET /api/v1/me/profile` → 200 with `UserProfile` (including `user_id`, common fields, `custom_data`, timestamps). Auto-creates as per FR-1.
- `PUT /api/v1/me/profile` (full replace of common fields; `custom_data` replaced if supplied) and `PATCH /api/v1/me/profile` (partial; `custom_data` Merge-Patched) → 200 with updated profile. Both validate via Pydantic `ProfileUpdate` (all fields optional, `extra="forbid"` at top-level — only `custom_data` is open). `custom_data` patch semantics as in FR-3.
- `GET /api/v1/auth/me` → 200 with existing identity payload *plus* embedded `profile: UserProfile` (auto-created as needed). No opt-in query param; saves the web a second round-trip. Maintains backward compatibility (additive key). Shape: `{ id, email, display_name, avatar_url, is_superuser, workspaces, permissions, profile }`.

**Consequences:**
- `GET /me/profile` without Authorization → 401.
- `PATCH /me/profile` with `{ custom_data: { foo: "bar" } }` after previous `{ keep: 1 }` yields merge as in FR-3.
- `GET /auth/me` for a fresh user returns `profile: { first_name: null, ..., custom_data: {} }` and `avatar_url: null` (empty/default) without 404.
- Validation error returns 422 with FastAPI `detail` surfaced via dataProvider (`error.message`).

#### FR-6: Cross-user profile read (workspace-bounded) — RESOLVED

`GET /api/v1/users/{user_id}/profile` returns a public projection of that user's profile if and only if requester and target share at least one `WorkspaceMember` row with `status=active`, or requester is `is_superuser`. Otherwise 404 (not 403 to avoid enumeration). [RESOLVED per review: workspace co-membership is the only gate — no public/org-wide reads]. Projection excludes private custom keys prefixed `_private_` or listed in settings and always redacts `phone_number`, `date_of_birth` from cross-user reads (owner's `GET /me/profile` still returns them).

**Consequences:**
- Member A in workspace W can `GET /users/B/profile` when B is also in W → 200.
- Member A not sharing any workspace with B → 404 (indistinguishable from "no such user").
- Response never leaks `users.password_hash`, `refresh_tokens`, or audit-internal fields; `custom_data._private_*` never appears in cross-user projection.

#### FR-7: Authorization and PII handling

Own-profile writes require `auth.sub == profile.user_id`; cross-user `GET` requires co-membership (FR-6) or superuser. No role permission gating in v1 (`member:read` not required). `phone_number`, `date_of_birth`, and any key under `custom_data` matching `_private` prefix are withheld from cross-user reads. Redaction happens in the serializer layer, not by stripping stored data.

**Consequences:**
- `PATCH /users/{other}/profile` always 404/403 (no such route; only `/me/profile` is writable).
- `GET /users/{other}/profile` as workspace co-member returns `phone_number: null` even if owner set it (redacted), while `GET /me/profile` as owner returns the true value.
- Audit `details` for mutations never include raw PII values, only `changed_fields` keys.

### 4.4 Template Extendability Contract

**Description:** The feature's primary non-functional novelty: how a fork extends the model without forking the helpers. Contract is documented and enforced by tests that write an unknown key and read it back without a schema change. Realizes UJ-4.

**Functional Requirements:**

#### FR-8: Backend extension seam (one migration + one schema file)

Adding a first-class field requires only: (1) add column to `UserProfile` model (`apps/api/src/models/profile.py`), (2) add optional field to `ProfileRead`/`ProfileUpdate` Pydantic schemas (`apps/api/src/schemas/api.py`), (3) generate Alembic migration. No change to `ProfileService`, serializers, or `getProfileField` logic. New column is automatically exposed via `GET/PUT/PATCH` and via the accessor's top-level-first lookup. Unknown top-level keys on inbound payloads are rejected with 422 (except inside `custom_data`).

**Consequences:**
- Fork adds `years_of_experience: Mapped[int | None]` column; after migration, `PATCH /me/profile { years_of_experience: 5 }` succeeds without service edits.
- `PATCH /me/profile { unknown_top_level: "x" }` where `unknown_top_level` not a column and not inside `custom_data` → 422.
- Existing clients that ignore unknown response fields continue to work (additive change).

#### FR-9: Frontend extension seam (one type file)

`apps/web/src/types.ts:1` exports `UserProfile` as `type UserProfile = { id: string; user_id: string; first_name?: string | null; ...; custom_data: Record<string, unknown>; created_at?: string; updated_at?: string; } & Record<string, unknown>` or equivalent documented pattern, plus `getProfileField` and `useProfile` hook. Fork extends `UserProfile` by adding an optional property to the declared part; generic list/detail components that render via `getProfileField` need no edits.

**Consequences:**
- Fork adds `department?: string | null` to `UserProfile`; `getProfileField(profile, "department")` resolves to top-level value.
- Component rendering `profile.custom_data["t_shirt_size"]` still works without type change (index access via `Record`), and with `getProfileField` no conditional is needed.
- `npm run build` (`tsc --noEmit`) passes when fork adds optional fields without touching shared `refine-ui` components (verified by type test).

#### FR-10: Schema promotion path

Documentation (README snippet or `docs/providers/profile.md`) explains how to promote a hot `custom_data` key to a column: add column, migration copies `custom_data->>'key'` to new column where present, service reads prefer column over JSON when both exist, deprecation note to stop writing to JSON for that key. Tests assert promotion does not lose data.

**Consequences:**
- After promotion, `GET /me/profile` for a record that previously stored `{ custom_data: { department: "eng" } }` returns `department: "eng"` at top-level and optionally still `custom_data.department` for one migration window or immediately cleared — behavior documented and tested.

### 4.5 Frontend Data Layer & UI

**Description:** Refine.dev dataProvider does not need a new resource for `user_profiles`; profile is fetched via `useCustom` relative to `/api/v1` (per Apps docs rule) and via the embedded `profile` in `useGetIdentity` (`GET /auth/me`). A thin `useProfile` wrapper encapsulates the standalone endpoint. The `/settings/profile` route is a non-resource settings route. Forms use `useForm` (`@refinedev/react-hook-form`) + `zodResolver` + shadcn Form primitives, per frontend canonical rules.

**Functional Requirements:**

#### FR-11: Frontend fetch helpers

Web exposes: (a) `UserProfile` type + `getProfileField`, (b) `useProfile()` hook (wraps `useCustom` GET for `/me/profile` or derives from `useGetIdentity`'s embedded profile, preferring the latter to avoid duplicate fetches), (c) `useUpdateProfile()` hook (wraps mutation, invalidates `["profile","me"]` and `["auth","me"]`). All URLs relative to `/api/v1` and Vite proxy safe (`/api/` trailing slash). No hand-rolled `fetch` outside dataProvider.

**Consequences:**
- `useProfile()` after `useUpdateProfile({ first_name: "New" })` re-renders with new value without full reload (query invalidation — both profile and identity queries).
- Any component can call `getProfileField(useProfile().data, "any_key")` without knowing if `any_key` is a column or JSON key.
- Hard refresh of `/settings/profile` (SPA route) does not hit backend `404` (Vite proxy rule `/api/` respected).
- Initial app load (`GET /auth/me`) already hydrates profile; `GET /me/profile` is only needed for explicit settings-page freshness.

#### FR-12: Profile Settings page

Route `/settings/profile` renders a settings card (or `CreateView` adjacent layout), with form fields for each common field + `avatar_url` (URL input, not uploader — defer upload) + a key-value editor for `custom_data` using Merge Patch semantics (empty string vs. delete action; UI sends `null` to delete a key). Validation mirrors backend Pydantic limits (zod schema imported or duplicated with comment). Success notification via `successNotification` in `refineCoreProps`; error `detail` surfaced without duplicate toast (`errorNotification: false` when rendering manually).

**Consequences:**
- Submitting invalid `website_url` (not a URL) shows inline `FormMessage` and does not fire mutation.
- On 422 from API, server `detail` string appears once (as error toast or inline), not twice.
- Deleting a `custom_data` key in the UI results in `PATCH { custom_data: { thatKey: null } }`.

### 4.6 Observability, Audit & Lifecycle

**Description:** Profile changes are auditable and the product now supports the minimal GDPR-grade lifecycle: export bundle and self-service delete. No dedicated event stream in v1 beyond audit; notification workflow not triggered.

**Functional Requirements:**

#### FR-13: Audit trail for profile mutations

Every `PUT/PATCH /me/profile` publishes `audit.entry.created` with `resource_type="user_profile"`, `resource_id=user_id`, `action="profile.updated"`, `details` including changed keys (not full PII values beyond keys). Follows existing `events/subjects.py` `audit.*` + `src/events/publisher.py` pattern.

**Consequences:**
- After `PATCH /me/profile { first_name: "X" }`, an `AuditLogEntry` row exists with `action="profile.updated"` and `details` containing `changed_fields: ["first_name"]` (or `["custom_data.twitter_handle"]` for JSON keys).
- Audit entries are immutable and never deleted.

#### FR-14: User data export

`GET /api/v1/me/export` (auth required) returns `application/json` bundle `{ exported_at, user: { id, email, display_name, avatar_url, created_at }, profile: UserProfile, workspaces: [{ workspace_id, workspace_name, role, joined_at }], counts: { audit_entries, notifications } }` — a synchronous, point-in-time snapshot. Secrets (`password_hash`, `refresh_token hashes`, `api key secrets`) are never included. Optional superuser route `GET /api/v1/users/{id}/export` with same shape gated on co-membership or superuser. Content-Disposition `attachment; filename="export-{user_id}-{iso}.json"`.

**Consequences:**
- `GET /me/export` without auth → 401; with auth → 200 with JSON and never leaks `password_hash`.
- Export includes the caller's latest `custom_data` exactly as stored.
- Large exports remain synchronous in v1 (no async job); bundle size bounded by audit/notification counts not included in payload beyond counts — full audit export is deferred to workspace admin export.

#### FR-15: Self-service account deletion

`DELETE /api/v1/me` (auth required) hard-deletes the `User` row, cascading to `user_profiles`, `refresh_tokens`, `workspace_members`, `notifications` (if user-scoped), `invitations` where applicable, and revokes all sessions. Body: `{ password?: string, confirm: "DELETE" }` — password required when `users.password_hash IS NOT NULL`, otherwise only `confirm` (covers OAuth users). On success: 204, publishes `audit.entry.created` with `action="user.deleted"` (before delete), and instructs the client to clear tokens. Subsequent `GET /auth/me` → 401. No soft-delete in v1. A superuser `DELETE /api/v1/users/{user_id}` exists for admin erasure with the same cascade.

**Consequences:**
- `DELETE /me` with wrong password → 403/422; with correct payload → 204 and `SELECT * FROM users WHERE id=:id` returns zero rows, same for `user_profiles`.
- OAuth user (no password) deletes with `{ confirm: "DELETE" }` alone → 204.
- After delete, `X-Workspace-ID` requests with that user's token fail at auth (user not found / token revoked).

#### FR-16: PII / GDPR alignment

`DELETE /me` cascade covers erasure; `GET /me/export` covers portability; `custom_data` values are not indexed for search in v1; no profile data is written to logs. Audit entries for deletions retain only `user_id`, `email` (redacted/hashed per policy [ASSUMPTION: keep email in audit with note]), and `action`, not full PII.

**Consequences:**
- `DELETE FROM users WHERE id=:id` leaves zero `user_profiles` rows with that `user_id` (FK cascade verified).
- Application logs for `PATCH /me/profile` do not contain `bio`, `phone_number`, or `custom_data` values at INFO level (only `user_id` + changed keys).

## 5. Non-Goals (Explicit)

- `Agent` entity / `AgentProfile` — explicitly deferred; agents will own a separate `agents` / `agent_profiles` model and are listed in Glossary only to prevent conflation.
- Moving `users.display_name` or `users.avatar_url` into the profile or duplicating them bi-directionally in v1. `User` remains the source of truth for those two fields; profile may later override display via a separate decision. Avatar file upload remains deferred (URL string only, may be empty).
- Workspace-scoped profiles (per-workspace attributes). Profile is global per human user; workspace-specific preferences belong in a future `workspace_member_profiles` or scoped `custom_data` namespace.
- Search, filtering, indexing, or sorting users by `custom_data` keys. No GIN indexing or query DSL in v1.
- File uploads (avatars, documents) or media handling — deferred; `avatar_url` holds a URL string, may be empty.
- Role-based field-level permissions (e.g., only admins can edit `department`). All own-profile fields are writable by the owner; cross-user reads are workspace-bounded only.
- Real-time sync of profile updates over WebSockets. Clients refetch on next navigation or explicit invalidation.
- Automatic `custom_data` schema validation beyond JSON + size. Forks may introduce per-key zod/json-schema validation themselves.
- Admin "edit any profile" writes in v1 (reads already allowed for superuser/co-member; writes remain owner-only except superuser delete/export).
- Async/batched export of full audit history beyond counts (deferred to workspace admin export).

## 6. MVP Scope

### 6.1 In Scope

- Migration + model `UserProfile` (`user_profiles`) with common fields (FR-2) + `custom_data` JSON + `user_id` UNIQUE FK CASCADE; `avatar_url` stays on `users`, defaults empty.
- `ProfileService` with `get_or_create`, `update` (Merge Patch), `export_bundle`, `delete_account` helpers; auto-provision on register/OAuth and lazy creation on `GET /me/profile` or `GET /auth/me` (FR-1).
- Pydantic schemas `ProfileRead`, `ProfileUpdate` (partial semantics), and shared `ProfileBase` with `extra="forbid"` at top-level and open `custom_data`.
- REST endpoints `GET /me/profile`, `PUT/PATCH /me/profile`, `GET /users/{user_id}/profile` (workspace-bounded public projection `FR-6`), `GET /auth/me` (always embeds `profile`), `GET /me/export` (and superuser `/users/{id}/export`), `DELETE /me` (and superuser `/users/{id}`) as in FR-14/15.
- Audit publication `profile.updated` and `user.deleted` (FR-13).
- Seed/backfill for legacy users; cascade-verified delete.
- Frontend `UserProfile` type + `getProfileField` + `useProfile`/`useUpdateProfile` hooks and `/settings/profile` Settings page with shadcn Form + zod (FR-11, FR-12), with `avatar_url` URL input (no uploader) and Merge Patch-aware `custom_data` editor (null = delete).
- Documentation in `docs/providers/profile.md` or `README.md` explaining the extension seam and promotion path (FR-8, FR-9, FR-10).
- Unit + e2e coverage: model, service, routes, serializers, extendability invariant (unknown key round-trip), export bundle, and delete cascade.

### 6.2 Out of Scope for MVP

- `Agent` entity / `AgentProfile` — separate track; this PRD must not be reused for it.
- Avatar file upload / storage — deferred; field may be empty.
- Public search/directory with filtering by custom keys — deferred; needs indexing strategy and privacy review.
- Role-based field ACL or per-field visibility flags beyond the simple withheld-set in FR-7 — deferred; requires UX spec for visibility controls.
- WebSocket push for live profile propagation — deferred; polling/invalidation covers v1.
- Per-key `custom_data` validation (json-schema per key) or indexing — deferred; let forks decide.
- Admin "edit any profile" endpoint — deferred; superuser can read and delete/export, but writes remain owner-only.
- Full audit-history export inside `/me/export` — deferred; export returns counts, not rows.

## 7. Success Metrics

**Primary**
- **SM-1**: Adoption — ≥90% of `users` have a `user_profiles` row within 24h of release (measured via migration backfill + lazy creation logs). Validates FR-1.
- **SM-2**: Correctness — 100% of `PATCH /me/profile` Merge Patch cases (add, retain, null-delete) round-trip correctly on immediate `GET /me/profile` in e2e suite. Validates FR-3, FR-5.
- **SM-3**: Extendability invariant — fork-adds-column test passes: after adding a nullable column + schema field, `PATCH /me/profile { new_field: "x" }` succeeds and `getProfileField(profile, "new_field")` reads it with zero helper changes. Validates FR-8, FR-9.
- **SM-4**: Lifecycle — `GET /me/export` returns valid JSON including `profile` for any active user; `DELETE /me` cascade leaves zero orphan `user_profiles` and revokes sessions. Validates FR-14, FR-15.

**Secondary**
- **SM-5**: Latency — p95 `GET /me/profile` and `GET /auth/me` (with profile JOIN) < 150 ms in dev (pgserver) for single-row lookup. Validates indexing.
- **SM-6**: Developer experience — time to add a new profile field (model + schema + migration + type) < 15 minutes in docs walkthrough.
- **SM-7**: UI adoption — ≥50% of active users visit `/settings/profile` within first week (if analytics present), else dogfood sign-off.

**Counter-metrics (do not optimize)**
- **SM-C1**: Model bloat — number of common columns stays ≤12 in v1. Adding a 13th requires explicit PRD amendment. Counterbalances SM-3.
- **SM-C2**: `custom_data` size creep — p95 serialized `custom_data` < 2 KiB after 30 days; alert if >8 KiB (signals teams should promote keys). Counterbalances SM-2.

## 8. Open Questions

1. ~~**Exact common-field set.**~~ **RESOLVED:** FR-2 set approved as final.
2. ~~**Cross-user read policy.**~~ **RESOLVED:** Workspace co-membership only (FR-6/FR-7); always redact `phone_number`/`date_of_birth`.
3. ~~**`GET /auth/me` embed.**~~ **RESOLVED:** Always embed `profile` (no `?include=profile` param).
4. ~~**`custom_data` merge vs. replace.**~~ **RESOLVED:** RFC 7396 JSON Merge Patch — `PATCH` shallow-merges, `null` deletes, omission retains, `PUT` replaces bag; choice is the professional easy-to-use default.
5. ~~**`avatar_url` ownership.**~~ **RESOLVED:** Stays on `users`, may be empty, no upload in v1.
6. **Per-key validation and indexing.** Do any forks need immediate constraints like `custom_data.department ∈ {eng, sales, ...}` or indexing for directory filtering? Would pull GIN index and validation registry into MVP. Owner: Architect. **Status: deferred per OQ resolution preference.**
7. ~~**GDPR export/delete surface.**~~ **RESOLVED:** In scope — `GET /me/export` and `DELETE /me` (plus superuser variants) are required in MVP (FR-14/FR-15).

## 9. Assumptions Index

- `§2.2`: `Agent` is a separate entity with `AgentProfile`; `UserProfile` must not be reused for agents — a second model is required.
- `§3`, FR-1: Profile is global per user (not per workspace). Workspace-specific overrides are out of scope.
- `FR-2`: Exact common-field set and varchar limits as listed; frontend zod mirrors these limits. [RESOLVED/approved]
- `FR-2`: `avatar_url` stays on `users` in v1, may be empty/null; no file upload (deferred).
- `FR-1`: Lazy `get_or_create` on `GET /me/profile` and `GET /auth/me` is allowed (idempotent) alongside eager creation at registration.
- `FR-3`: `custom_data` limits — 16 KiB serialized, 50 top-level keys — are tunable via settings; Merge Patch: `null` deletes a key.
- `FR-4`: Frontend helper lives beside `src/types.ts` (e.g., `src/lib/profile.ts` or `src/types.ts`-adjacent) and is named `getProfileField`.
- `FR-6`: `GET /users/{id}/profile` for non-co-members returns 404 (not 403) to avoid enumeration. [RESOLVED: co-membership is sole gate]
- `FR-7`: Cross-user reads withhold `phone_number`, `date_of_birth`, and keys prefixed `_private_` in v1; detailed visibility flags deferred.
- `FR-8`/`FR-9`: Frontend `UserProfile` uses intersection `& Record<string, unknown>` pattern for open-ended indexing; unknown top-level inbound keys are 422.
- `FR-10`: Promotion-path docs live in `docs/providers/profile.md` (or `README.md` if providers folder not used).
- `FR-13`: Audit `details` logs only changed field *keys*, not full PII values.
- `§6.1`: `GET /auth/me` always embeds `profile` (additive change). [RESOLVED]
- `FR-3`/`FR-5`: `PUT /me/profile` with explicit `custom_data` replaces the bag entirely; `PATCH` is Merge Patch.
- `FR-14/FR-15`: `GET /me/export` is synchronous snapshot with counts (not full audit rows); `DELETE /me` requires `confirm:"DELETE"` plus password when applicable, and is a hard delete via FK cascade.

---

## 10. Cross-Cutting NFRs

- **Performance:** Single-row PK lookup on `user_profiles.user_id`; no N+1 on `GET /auth/me` (JOIN or batched `select`). p95 GET <150 ms with embed (SM-5). `custom_data` capped to prevent row bloat.
- **Security:** All endpoints behind `get_current_user`; cross-user reads enforced via `WorkspaceMember` existence check. No profile data in error messages or logs beyond `user_id` + keys. `custom_data` values never used in raw SQL string interpolation.
- **Reliability:** Auto-provision is transactional; race on lazy creation handled via `INSERT ... ON CONFLICT DO NOTHING` / unique-constraint retry. Migration is idempotent and reversible (drops table/column). `DELETE /me` is atomic (single transaction for cascade).
- **Observability:** Audit entries for mutations and deletions (FR-13/FR-15); structured logs for provision/backfill/export/delete counts; no PII at INFO.
- **Data governance:** `custom_data` not indexed/searched in v1; cascade delete aligns with user deletion; export is the portability seam.

## 11. Constraints & Guardrails

- **Stack-parity:** Must reuse existing patterns — `apps/api/src/models/workspace.py:11` SQLAlchemy style, `TimestampMixin`, `StringUUID`, `JSON`, and `apps/api/src/schemas/api.py:1` Pydantic style — no new ORM or validation libraries.
- **Template footprint:** Minimal new dependencies; no new infra. Vite proxy `/api/` rule and existing `dataProvider` contract must remain intact (`apps/api/src/settings.py:1` CORS, etc.).
- **Type safety:** `apps/web/src/types.ts:1` remains the single high-impact type entry; `npm run build` (`tsc --noEmit`) must pass after the change and after the documented extension step.
- **Blast radius:** High-impact files `apps/api/src/db/session.py` (imported by 17 files), `apps/api/src/models/workspace.py` (13), `apps/web/src/types.ts` (12) may be *imported*, not refactored. New model goes in `apps/api/src/models/profile.py` to avoid perturbing those.
- **No Agent coupling:** No code in this feature may assume or import future `Agent` types; keep the seam ready but empty.

## 12. API Contracts (Public Surface)

### REST

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/me/profile` | JWT | Own profile (auto-creates) |
| `PUT` | `/api/v1/me/profile` | JWT | Replace common fields; `custom_data` replaced if supplied |
| `PATCH` | `/api/v1/me/profile` | JWT | Partial update; `custom_data` Merge-Patched (null deletes) |
| `GET` | `/api/v1/users/{user_id}/profile` | JWT | Co-member's public projection (404 if no shared workspace) |
| `GET` | `/api/v1/auth/me` | JWT | Identity + embedded `profile` (always, auto-creates) |
| `GET` | `/api/v1/me/export` | JWT | GDPR export bundle (JSON, attachment) |
| `GET` | `/api/v1/users/{user_id}/export` | JWT (superuser/co-member) | Superuser export of another user |
| `DELETE` | `/api/v1/me` | JWT + password/`confirm` | Self-service hard delete (cascade, 204) |
| `DELETE` | `/api/v1/users/{user_id}` | JWT (superuser) | Admin hard delete |

**Schemas (Pydantic)**

- `ProfileBase`: `first_name?: str[1..100]`, `last_name?: str[1..100]`, `bio?: str[0..1000]`, `phone_number?: str[0..30]`, `timezone?: str[0..50]`, `locale?: str[0..10]`, `date_of_birth?: date`, `website_url?: AnyHttpUrl|None`, `location?: str[0..200]`.
- `ProfileUpdate(ProfileBase)`: all optional; `custom_data?: dict[str, Any]`; `model_config = ConfigDict(extra="forbid")` (top-level closed) + explicit `custom_data` field open. `PATCH` semantics: Merge Patch; `PUT` replacement.
- `ProfileRead(ProfileBase)`: `id: UUID`, `user_id: UUID`, `custom_data: dict`, `created_at: datetime`, `updated_at: datetime`.
- `DeleteMeRequest`: `password?: str`, `confirm: Literal["DELETE"]`; validated: if `users.password_hash IS NOT NULL` then `password` required and verified.
- `ExportBundle`: `{ exported_at, user, profile, workspaces, counts }`.

**Frontend contracts**

- `UserProfile` in `apps/web/src/types.ts` — declared fields optional/nullable + `custom_data: Record<string, unknown>` + `& Record<string, unknown>` index for future columns.
- `getProfileField(profile, key, fallback): unknown` — column-first, then `custom_data[key]`, then fallback. Complements direct `profile.custom_data[key]` access.
- `useProfile(): UseQueryResult<UserProfile>` (standalone) and identity-embedded profile via `useGetIdentity` (`Identity.profile`).
- `useUpdateProfile(): UseMutationResult<UserProfile>` (invalidates `["profile","me"]` + `["auth","me"]`), `useExportProfile()`, `useDeleteAccount()`.

**Breaking-change policy:** Adding optional top-level columns is non-breaking (clients ignore unknowns). Removing or renaming is breaking. `custom_data` keys are always non-breaking.

## 13. Integration & Dependencies

- **DB:** Alembic migration creates `user_profiles`; `pgserver` (dev) and Postgres (prod) both supported via `StringUUID` + `JSON` column types. Migration also backfills legacy users. Delete cascade uses FK `ON DELETE CASCADE` for profiles; `DELETE /me` service explicitly deletes related rows in order where FKs don't cover (refresh_tokens, audit retention note).
- **Auth:** `AuthService.register` / `upsert_oauth_user` call `ProfileService.get_or_create` within same session/flush — no new auth flows. `AuthService` also gains `delete_user` helper used by `DELETE /me`.
- **Workspaces/Members:** No FK to workspaces; profile reads check `WorkspaceMember` existence via existing `WorkspaceService` or direct query. No change to invitation/member flows.
- **Audit:** Reuses existing `audit.entry.created` workflow (`src/events/subjects.py`, `src/events/publisher.py`, `AuditLogEntry`). New actions: `profile.updated`, `user.deleted`, `user.exported` (optional).
- **Web data layer:** Reuses `dataProvider` + `useCustom`. No changes to `accessControlProvider` (`PERMISSION_MAP`) unless `profile:read|write` is later introduced [ASSUMPTION: not in MVP].
- **No integration with NATS realtime, email, or jobs** in v1 beyond audit publish.

## 14. Rollout & Migration

1. Land migration + backfill (idempotent; inserts missing profiles) + note that `avatar_url` on `users` may be `null`/empty without action.
2. Deploy API (new routes backward-compatible — `GET /auth/me` additive `profile` key; old clients unaffected).
3. Deploy web (new `/settings/profile` route + helpers + delete/export UI; `useGetIdentity` type extended with `profile: UserProfile`).
4. Document extension seam and promotion path; add `docs/providers/profile.md`.
5. Post-deploy verification: `GET /me/profile` smoke, `GET /auth/me` embed check, `GET /me/export` smoke, `DELETE /me` in staging (create throwaway user), audit log check, `npm run build` passes.

## 15. Platform

Web primary. Responsive settings form; desktop-first for directory. No native/PWA specifics. All API surface is platform-agnostic REST under `/api/v1`.

## 16. Data Governance

- **PII:** Profile fields constitute PII. Redaction rules (FR-7) enforced at serializer layer. `custom_data` may contain PII — treat as PII by default.
- **Residency:** Inherits `DATABASE_URL` residency; no separate store.
- **Retention:** Lives with `User` row; hard-deleted on `DELETE /me` via cascade. Audit entries for `user.deleted` retained but without PII payload.
- **Access logging:** Profile reads do not create audit entries; mutations, exports, and deletions do.
