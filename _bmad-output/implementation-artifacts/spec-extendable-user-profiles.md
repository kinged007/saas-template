---
title: 'Extendable User Profiles'
type: 'feature'
created: '2026-08-29'
status: 'done'
review_loop_iteration: 0
context: [_bmad-output/planning-artifacts/prds/prd-saas-template-2026-08-29/prd.md, _bmad-output/planning-artifacts/architecture/architecture-saas-template-2026-08-29/ARCHITECTURE-SPINE.md, _bmad-output/planning-artifacts/epics-profiles-2026-08-29.md]
baseline_commit: 'f77055fc940bd214207227a50b51fd689d680c9b'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** No user-facing profile beyond `users` columns; forks cannot add profile fields without editing shared helpers, `custom_data` lacks a merge contract, and GDPR export/delete are missing. Frontend has no typed `UserProfile` or uniform accessor.

**Approach:** Add `user_profiles` 1:1 `users.id` (`custom_data JSON DEFAULT {}`), provision on register/oauth/lazy `get_or_create`, expose `GET/PUT/PATCH /me/profile`, `GET /auth/me` embedding, `GET /users/{id}/profile` workspace-bounded redacted read, `GET /me/export` and `DELETE /me` lifecycle, with frontend `UserProfile` + `getProfileField` + hooks + `/settings/profile` page using RFC 7396 Merge Patch for `custom_data`.

## Boundaries & Constraints

**Always:** All profile routes behind `get_current_user` (JWT); `ProfileService` owns the `AsyncSession` tx; `GET /auth/me` and `GET /me/profile` return identical `profile` shape; `GET /users/{id}/profile` 404 when not co-member nor superuser (no 403 enumeration); `PUT/PATCH /me/profile` publish `audit.entry.created` with `changed_fields` only (no PII values); frontend uses `dataProvider`/`useCustom` relative to `/api/v1`, never raw `fetch`.

**Ask First:** Changing `users` table or `StringUUID/TimestampMixin` contracts; adding required env var; introducing new event subject beyond `audit.entry.created`; making `custom_data` indexed/GIN or searchable.

**Never:** Store profiles in `users` columns or pollute `workspace.py`; expose `password_hash`/token material in `GET /auth/me` or export; log `bio`/`custom_data` values at `INFO`; modify shared `refine-ui` components to special-case profile; use workspace-scoped `user_profiles`; reuse `user_profiles` for planned `Agent` entity.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Create-on-read | `GET /me/profile` or `GET /auth/me` with no row | 200 with `custom_data:{}` and common fields null, row inserted | concurrent inserts use `ON CONFLICT DO NOTHING` + re-select, no 500 |
| PATCH Merge Patch | `PATCH /me/profile {"custom_data":{"a":1}}` then `{"custom_data":{"b":2}}` | second result `{"a":1,"b":2}` | `422` if merged bag >16 KiB or >50 keys |
| PATCH null delete | `PATCH {"custom_data":{"a":null}}` where `a` exists | key `a` removed, others retained | deleting absent key is no-op |
| PUT replace | `PUT {"custom_data":{"only":1}}` | bag is exactly `{"only":1}` regardless of prior | `PUT` without `custom_data` leaves bag unchanged |
| Unknown top-level | `PATCH {"unknown_field":1}` | not accepted | `422` via `extra=forbid` single error toast |
| Bounds reject | `PATCH custom_data` 17 KiB or 51 keys | rejected | `422` `custom_data exceeds limits` |
| Own write audit | valid `PUT/PATCH` | `audit.entry.created resource_type=user_profile action=profile.updated details={changed_fields:[...]}` before response | no PII values in audit |
| Cross-user allowed | caller & target share active `workspace_members` | 200 redacted projection | `phone_number`, `date_of_birth`, `_private*` stripped |
| Cross-user denied | no shared workspace and not superuser | `404` (not 403) | indistinguishable from missing user |
| Export | `GET /me/export` | `200` JSON `{exported_at,user,profile,workspaces,counts}` `Content-Disposition: attachment` | secrets excluded; superuser variant `GET /users/{id}/export` gated 403 |
| Self-delete with password | `DELETE /me {confirm:"DELETE", password:"correct"}` on local account | `204`, cascade deletes tokens/members/profile/user, publishes `user.deleted`, old token `401` | wrong `confirm`→422, wrong password→403, missing password when hash exists→422 |
| Self-delete oauth | `DELETE /me {confirm:"DELETE"}` on oauth user (no password_hash) | `204` without password | same confirm check |
| getProfileField | `getProfileField({first_name:"A", custom_data:{x:1}},"x")` | `1`; unknown key→fallback; column takes precedence over `custom_data` | returns `fallback ?? null` |

</frozen-after-approval>

## Code Map

- `apps/api/src/models/workspace.py:11` -- `class User(Base,TimestampMixin)` high-impact(13) -- keep untouched, reuse FK pattern
- `apps/api/src/db/base.py:12` -- `StringUUID` dialect-aware UUID -- reuse for `user_profiles.user_id` PK/FK
- `apps/api/src/db/base.py:50` -- `TimestampMixin` `created_at/updated_at` -- inherit
- `apps/api/src/db/session.py:14` -- `SessionFactory` + `get_db()` -- reuse Depends
- `apps/api/src/models/__init__.py:1` -- model re-exports -- add `UserProfile` import so alembic auto-registers
- `apps/api/src/schemas/api.py:1` -- Pydantic `BaseModel+Field` patterns -- add `ProfileBase/ProfileRead/ProfileUpdate/ProfileExport/DeleteMeRequest`
- `apps/api/src/services/auth.py:33` -- `AuthService(session,bus)` + `register:48` `publish_audit:67` -- mirror for `ProfileService`
- `apps/api/src/services/serializers.py:9` -- `_to_iso` / `user_to_dict:30` -- add `profile_to_dict` + `public_projection` redaction
- `apps/api/src/api/routes/auth.py:22,95` -- `APIRouter /auth` + `GET /me` -- add profile embed via `get_or_create`
- `apps/api/src/api/deps.py:76` -- `get_current_user` / `AuthPrincipal:29` -- guard every profile route
- `apps/api/src/main.py:68,92` -- `FastAPI` app + `include_router` -- add `profiles.router` at `/api/v1`
- `apps/api/alembic/env.py:17,26` -- `from src import models` + `Base.metadata` -- auto migration
- `apps/api/alembic/versions/0005_conversations.py:16` -- latest `revision 0005` -- new `0006_user_profiles.py` `down_revision="0005"`
- `apps/api/src/events/publisher.py:51` -- `publish_audit` -- call with `resource_type=user_profile action=profile.updated`
- `apps/api/src/settings.py:8` -- `Settings` -- no new required env, bounds are code constants
- `apps/web/src/types.ts:13,113` -- `Identity` / `Workspace` -- add `UserProfile` + `getProfileField` + `Identity.profile?`
- `apps/web/src/providers/dataProvider.ts:11,80` -- `API_URL /api/v1` + enriched `error.message` -- use `useCustom` not raw fetch
- `apps/web/src/providers/authProvider.ts:85` -- `getIdentity` `GET /auth/me` -- caches shape mirrored by backend
- `apps/web/src/hooks/use-mobile.tsx:5` -- only existing hook -- add `hooks/useProfile.ts` alongside
- `apps/web/src/components/ui/form.tsx:16` -- `Form/FormField/FormItem/FormLabel/FormControl/FormMessage` -- use in settings page
- `apps/web/src/pages/ApiKeyCreatePage.tsx:44,64` -- `useForm @refinedev/react-hook-form + zodResolver + CreateView` canonical -- reuse for profile form pattern
- `apps/web/src/App.tsx:47,64` -- `resources` + `Routes <Authenticated><AppLayout>` -- add `/settings/profile` route
- `apps/web/src/components/AppLayout.tsx:152` -- `UserMenu` -- add Profile Settings link
- `apps/web/vite.config.ts:16` -- proxy `"/api/"` trailing slash -- keep, urls relative to `/api/v1` so SPA `/settings/profile` not swallowed

## Tasks & Acceptance

**Execution:**
- [x] `apps/api/src/models/user_profile.py` -- create `UserProfile(Base, TimestampMixin)` `user_id` PK FK cascade unique + 9 common cols + `custom_data JSON DEFAULT {}` -- reuse StringUUID/TimestampMixin
- [x] `apps/api/src/models/__init__.py` -- re-export `UserProfile` for metadata
- [x] `apps/api/alembic/versions/0006_user_profiles.py` -- create table + backfill `INSERT SELECT users.id` idempotent + drop; `down_revision="0005"`; handle pg vs sqlite `String(36)`/`UUID`
- [x] `apps/api/src/schemas/api.py` -- add `ProfileBase(limits)`, `ProfileRead`, `ProfileUpdate(extra=forbid, custom_data?)`, export/delete schemas; `Field(max_length=…)` mirroring PRD sizes
- [x] `apps/api/src/services/profile_helpers.py` -- add `merge_custom_data(existing, patch, is_put) -> dict` (null-delete, bounds 50/16KiB) + bounded validator
- [x] `apps/api/src/services/profiles.py` -- `ProfileService(session,bus)` `get_or_create` (ON CONFLICT), `get`, `update(put? merge else replace)`, `get_public_projection(user, viewer)`, `export_bundle`, `delete_account`; transactions + `publish_audit`
- [x] `apps/api/src/services/serializers.py` -- `profile_to_dict`, `public_projection(profile)` redacts `phone_number/date_of_birth/_private*`
- [x] `apps/api/src/services/auth.py` -- wire `ProfileService.get_or_create` into `register` + `upsert_oauth_user` same session (lazy backfill)
- [x] `apps/api/src/api/routes/profiles.py` -- implement `GET /me/profile`, `PUT /me/profile`, `PATCH /me/profile`, `GET /users/{id}/profile`, `GET /me/export`, `GET /users/{id}/export` (superuser), `DELETE /me`, `DELETE /users/{id}` (superuser) -- all behind `get_current_user`
- [x] `apps/api/src/api/routes/auth.py:95` -- embed `profile: profile_to_dict(await get_or_create(user.id))` in `GET /auth/me` response alongside workspaces
- [x] `apps/api/src/main.py:92` -- `include_router(profiles.router, prefix="/api/v1")`
- [x] `apps/api/tests/test_profiles.py` -- unit: merge matrix, null-delete, bounds, unknown top-level 422, redaction, concurrent get_or_create, audit emission, export excludes secrets, delete cascade+401
- [x] `apps/web/src/types.ts` -- add `UserProfile` type + `Identity.profile?: UserProfile` + `export function getProfileField(p,key,fallback?)`
- [x] `apps/web/src/hooks/useProfile.ts` -- `useProfile` (`useCustom GET /me/profile`), `useUpdateProfile` (`useCustomMutation PATCH/PUT + invalidate ["auth","me"]`), `useExportProfile`, `useDeleteAccount` -- relative urls `/me/profile` via API_URL
- [x] `apps/web/src/pages/settings/ProfileSettingsPage.tsx` -- shadcn `Form`+`zodResolver` fields for 9 cols + avatar_url URL + key-value `custom_data` editor (null deletes), `successNotification`, `errorNotification:false` rendering `detail` once, `useNavigation().list` cancel, cache invalidation
- [x] `apps/web/src/App.tsx` + `apps/web/src/components/AppLayout.tsx` -- register `Route path="settings/profile"` inside `<AppLayout>` and add menu link; ensure `npm run build` passes
- [x] `docs/ARCHITECTURE.md` + `docs/providers/profile.md` -- add `UserProfile` domain model + 3-step add-column extension recipe + promotion `jsonb` one-liner

**Acceptance Criteria:**
- Given fresh DB with legacy users, when `alembic upgrade head`, then `user_profiles` rows == `users` rows and idempotent rerun leaves count unchanged
- Given authenticated user, when `GET /auth/me` then response contains `profile.custom_data` (empty `{}` if new) same shape as `GET /me/profile`
- Given `PATCH {"custom_data":{"a":1}}` then `PATCH {"custom_data":{"b":2}}`, when fetched then bag is `{"a":1,"b":2}`; when `PATCH {"custom_data":{"a":null}}` then `a` absent and `b` remains
- Given `PUT {"custom_data":{"only":1}}`, when fetched then bag is exactly `{"only":1}` regardless of prior
- Given `PATCH {"unknown_field":1}`, when called then `422` and frontend shows `detail` once (no duplicate toast)
- Given `custom_data` exceeding 16 KiB or 50 keys, when `PATCH/PUT` then `422`
- Given co-member caller and `phone_number/_private_secret` set on target, when `GET /users/{id}/profile` then `200` without those keys and dates; given non-co-member then `404`
- Given any authenticated user, when `PUT/PATCH /me/profile` then `audit.entry.created` row exists with `changed_fields` keys and no PII values; `GET /me/export` returns valid JSON with `profile` and without `password_hash`
- Given `DELETE /me {confirm:"DELETE", password:"pw"}` with wrong pw then `403`, with correct `confirm`+pw then `204` and subsequent `GET /auth/me` with old token is `401`, profile/tokens rows gone; OAuth user deletes with `confirm` alone
- Given adding new col `years_of_experience` (backend col + schema) and extending `UserProfile` type only, when `PATCH` new field and `getProfileField` on it then succeeds without editing `ProfileService`/`getProfileField` helper
- Given `npm run build` and `pytest apps/api/tests/test_profiles.py` then both green

## Design Notes

Frontend `getProfileField` resolves: `profile[key] !== undefined ? profile[key] : profile.custom_data?.[key] ?? fallback` — column wins, no fork helper edit. `useUpdateProfile` invalidates both `["data","auth","me"]` via `queryClient` and `identityStore` so header `useGetIdentity` refetches. Merge helper is pure and tested without DB. Export is synchronous snapshot because call is user-scoped (single row + counts), never lists full audit rows. `public_projection` is thin view over `profile_to_dict` to keep storage intact. Duration: secrets never in `profile_to_dict` output.

## Verification

**Commands:**
- `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` -- expected: idempotent backfill, no duplicate-key 500
- `uv run pytest apps/api/tests/test_profiles.py -q` -- expected: merge matrix, bounds, redaction, concurrency, export/delete cascade pass
- `npm run build --prefix apps/web` -- expected: `tsc --noEmit` + `vite build` green with new `UserProfile` type
- `uv run pytest apps/api -k profile --maxfail=1 -q` -- expected: all profile API e2e pass
- `grep -R "getProfileField" apps/web/src --include="*.ts" --include="*.tsx"` -- expected: only types.ts + useProfile.ts definitions and page usage

## Spec Change Log

## Suggested Review Order

**Entry point — data contract**

- Start here: 1:1 model defines whole seam
  [`user_profile.py:12`](../../apps/api/src/models/user_profile.py#L12)

**Persistence & migration**

- Migration creates table + idempotent backfill (pg vs sqlite)
  [`0006_user_profiles.py:25`](../../apps/api/alembic/versions/0006_user_profiles.py#L25)
- Model re-export registers metadata for alembic
  [`__init__.py:10`](../../apps/api/src/models/__init__.py#L10)
- TimestampMixin/StringUUID reuse keeps FK consistent
  [`base.py:12`](../../apps/api/src/db/base.py#L12)

**Merge-patch & validation**

- Shallow RFC7396 merge: null deletes, bounds 50/16 KiB
  [`profile_helpers.py:28`](../../apps/api/src/services/profile_helpers.py#L28)
- Pydantic limits mirror DB (extra=forbid, AnyHttpUrl)
  [`api.py:101`](../../apps/api/src/schemas/api.py#L101)

**Service layer — transactions & audit**

- get_or_create handles races via IntegrityError rollback
  [`profiles.py:34`](../../apps/api/src/services/profiles.py#L34)
- Update tracks changed_fields, merges custom_data, flags JSON
  [`profiles.py:57`](../../apps/api/src/services/profiles.py#L57)
- Public projection guards co-membership and redacts PII
  [`profiles.py:183`](../../apps/api/src/services/profiles.py#L183)
- Export builds bundle with counts, excludes secrets
  [`profiles.py:221`](../../apps/api/src/services/profiles.py#L221)
- Delete hard-deletes tokens/members/keys/notifications + audit
  [`profiles.py:280`](../../apps/api/src/services/profiles.py#L280)
- Serializers redact phone/_private and handle avatar separation
  [`serializers.py:59`](../../apps/api/src/services/serializers.py#L59)

**API surface**

- Own-profile GET/PUT/PATCH auto-creates, Merge-Patch vs replace
  [`profiles.py:24`](../../apps/api/src/api/routes/profiles.py#L24)
- Cross-user read returns 404 not 403 to avoid enumeration
  [`profiles.py:77`](../../apps/api/src/api/routes/profiles.py#L77)
- Export with sanitized Content-Disposition attachment header
  [`profiles.py:91`](../../apps/api/src/api/routes/profiles.py#L91)
- Delete requires confirm DELETE + password, 204
  [`profiles.py:131`](../../apps/api/src/api/routes/profiles.py#L131)
- Auth embed reuses same service for GET /auth/me
  [`auth.py:96`](../../apps/api/src/api/routes/auth.py#L96)
- Router registration at /api/v1
  [`main.py:92`](../../apps/api/src/main.py#L92)

**Frontend data layer**

- Typed UserProfile & column-wins getProfileField with prototype guard
  [`types.ts:13`](../../apps/web/src/types.ts#L13)
- Hooks use useCustom relative to /api/v1, invalidate auth
  [`useProfile.ts:13`](../../apps/web/src/hooks/useProfile.ts#L13)
- Settings form uses shadcn + zodResolver + custom_data editor
  [`ProfileSettingsPage.tsx:44`](../../apps/web/src/pages/settings/ProfileSettingsPage.tsx#L44)
- Route inside AppLayout keeps Vite /api/ proxy safe
  [`App.tsx:47`](../../apps/web/src/App.tsx#L47)
- Menu link exposes settings without shared component edits
  [`AppLayout.tsx:189`](../../apps/web/src/components/AppLayout.tsx#L189)

**Docs & tests**

- Extension recipe + promotion one-liner
  [`profile.md:1`](../../docs/providers/profile.md#L1)
- Domain model update for future agents
  [`ARCHITECTURE.md:25`](../../docs/ARCHITECTURE.md#L25)
- 27 tests cover merge matrix, redaction, concurrency, export/delete cascade
  [`test_profiles.py:1`](../../apps/api/tests/test_profiles.py#L1)

