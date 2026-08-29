# Implementation Plan — Extendable User Profiles

**PRD:** `_bmad-output/planning-artifacts/prds/prd-saas-template-2026-08-29/prd.md` (final)
**Spine:** `_bmad-output/planning-artifacts/architecture/architecture-saas-template-2026-08-29/ARCHITECTURE-SPINE.md` (final)
**Stack:** `fastapi>=0.115` · `sqlalchemy[asyncio]>=2.0` · `alembic>=1.14` · `@refinedev/core 5.0.12` · `react 18.3` · `typescript 5.6.3`
**Blast radius guard:** touch high-impact files only as import (see Spine §11); new code in `models/profile.py`, `services/profiles.py`, `api/routes/profiles.py`, `schemas/api.py:Profile*`, `types.ts:UserProfile`, `hooks/useProfile.ts`.

---

## Epic A — Model & Persistence (AD-2)

**Goal:** `user_profiles` exists, is seeded, and races are handled. Unlocks all other epics. *Binds FR-1, FR-2, FR-16.*

| Story | FRs | Spec | Size | Done when |
|---|---|---|---|---|
| **A1. Model + migration** | FR-2 | `apps/api/src/models/profile.py::UserProfile(Base, TimestampMixin)`, `StringUUID FK(users.id) CASCADE UNIQUE`, `custom_data JSON DEFAULT {}` + `0006_user_profiles.py` (create + backfill legacy: `INSERT … SELECT` + unique retry) | M | `alembic upgrade head` creates table; SQLite + asyncpg parity; reversible downgrade; `SELECT count(*) FROM user_profiles` = `users` |
| **A2. Provision hooks + get_or_create** | FR-1 | `src/services/profiles.py::ProfileService.get_or_create(user_id)` (select → `INSERT ON CONFLICT DO NOTHING` via `pg_insert` branch / plain try for SQLite) wired into `AuthService.register` & `upsert_oauth_user` same session; lazy path also in `GET /me/profile` and `GET /auth/me` | M | `POST /auth/register` ends with `user_profiles` row same tx; concurrent `GET /me/profile` ×2 → 200 identical `user_id`, no 500; legacy user without row backfills on first `GET /auth/me` |
| **A3. Pydantic schemas + serializer** | FR-2, FR-7 | `ProfileBase` (optional fields, `Field(max_length=…)`), `ProfileUpdate(extra=forbid, custom_data?: dict)`, `ProfileRead`, `profile_to_dict` + `public_projection` (redacts `phone_number`, `date_of_birth`, `_private*` keys) in `serializers.py` | S | `422` for `bio>1000` / unknown top-level key, round-trip exact JSON, `422` for `extra` at top-level |

**Deps:** none. **Owner:** backend. **Risks:** concurrent insert → test with 2 coroutines racing same user.

---

## Epic B — Profile APIs & Lifecycle (AD-3, AD-5, AD-7)

**Goal:** Own-profile CRUD, workspace-bounded reads, export, and self-delete. *Binds FR-3, FR-4, FR-5, FR-6, FR-14, FR-15, FR-16.*

| Story | FRs | Spec | Size | Done when |
|---|---|---|---|---|
| **B1. Own-profile endpoints** | FR-3, FR-4, FR-5 | `apps/api/src/api/routes/profiles.py`: `GET /api/v1/me/profile` (auto-creates), `PUT /api/v1/me/profile`, `PATCH /api/v1/me/profile` (Merge Patch: shallow-merge `custom_data`, `null`→delete, validate size `≤16KiB`/keys `≤50` after merge), wired in `apps/api/src/main.py`. `GET /api/v1/auth/me` embeds `profile` (800ms-add lateral `await profile_service.get_or_create`) | M | e2e: fresh user → `GET /auth/me` contains `profile:{custom_data:{}}`; `PATCH {custom_data:{keep:1}}` → `PATCH {custom_data:{foo:"bar"}}` yields `{keep:1,foo:"bar"}`; `PATCH {custom_data:{keep:null}}` deletes; `PUT {custom_data:{only:1}}` replaces |
| **B2. Cross-user public read + redaction** | FR-6, FR-7 | `GET /api/v1/users/{id}/profile` — guard: `SELECT 1 FROM workspace_members WHERE (user_id=me AND workspace_id IN (…target workspaces)) OR is_superuser`; else `404`; projection via `public_projection` serializer | S | co-member in shared workspace → 200 (redacted phone/bday); no shared workspace → 404 indistinguishable; `_private_*` never leaks |
| **B3. Auth wiring & audit** | FR-5, FR-13 | `GET /auth/me` embed uses existing `get_current_user`; each `PUT/PATCH` does `publish_audit(workspace_id=None, resource_type="user_profile", action="profile.updated", details={"changed_fields":[...]})` before return | S | audit row exists with `changed_fields` keys, no raw PII in `details`; logs show `user_id`+keys only |
| **B4. Export bundle** | FR-14 | `GET /api/v1/me/export` (+ superuser `GET /users/{id}/export`) → `application/json` `{exported_at, user, profile, workspaces:[…membership…], counts}` with `Content-Disposition: attachment`; secrets excluded | M | `GET /me/export` 200 JSON valid, contains `profile.custom_data` exactly, never contains `password_hash`/`refresh_tokens`; superuser path gated |
| **B5. Account deletion** | FR-15, FR-16 | `DELETE /api/v1/me` body `{password?: str, confirm:"DELETE"}` — verify `PasswordHasher.verify` when `password_hash IS NOT NULL`; single tx: delete `refresh_tokens`, `workspace_members`, `notifications`, then `users` (FK cascades `user_profiles`); `publish_audit(action="user.deleted")` before delete; `204`; `DELETE /users/{id}` superuser variant | M | throwaway user: `DELETE /me` with wrong pw→403; with correct→204, `SELECT users/profile/tokens` all zero, `GET /auth/me` with old token→401; OAuth user deletes with `confirm` only |
| **B6. Merge Patch helper & unit tests** | FR-3, FR-4 | Pure function `merge_custom_data(existing: dict, patch: dict\|None, is_put: bool) -> dict` (null-delete, size/key caps), `get_profile_field(profile, key, fallback)` server mirror, comprehensive bounds tests | S | `pytest` covers add/retain/null-delete, oversize 422, 50-key cap, unknown top-level 422 |

**Deps:** A. **Owner:** backend. **Risks:** tx atomicity on delete — test FK cascade in pgserver + SQLite.

---

## Epic C — Template Extendability Contract (AD-4)

**Goal:** Prove forks need only two files. *Binds FR-8, FR-9, FR-10.*

| Story | FRs | Spec | Size | Done when |
|---|---|---|---|---|
| **C1. Backend seam test** | FR-8 | Scripted test: temporarily add `years_of_experience` column via `alter table … add column integer null` + Pydantic field, then `PATCH /me/profile {years_of_experience:5}` → 200 and `getProfileField` sees it without touching `ProfileService` | S | CI marker test passes; `PATCH {unknown_top_level:"x"}`→422 |
| **C2. Frontend seam test** | FR-9 | Extend `UserProfile` with optional `department?: string\|null` in a type-only test file, assert `getProfileField(p,"department")` resolves top-level; `npm run build` still passes | S | `tsc --noEmit` in branch with added optional field — no edits to `refine-ui` shared components |
| **C3. Promotion recipe doc** | FR-10 | `docs/providers/profile.md` (or README snippet): 3-step add-column recipe + one-liner `custom_data->>'key'` migration + note to prefer column over JSON when both exist | XS | Doc merged; referenced from PRD §13/#14 |

**Deps:** A, B1. **Owner:** docs + tests. **Risks:** doc drift — validate with code links (`:line_number`).

---

## Epic D — Frontend Data Layer & Settings UI (AD-6)

**Goal:** End-user can view/edit profile, export, and delete. *Binds FR-11, FR-12, FR-14, FR-15.*

| Story | FRs | Spec | Size | Done when |
|---|---|---|---|---|
| **D1. Types + accessor + hooks** | FR-4, FR-11 | `apps/web/src/types.ts`: `UserProfile` + `Identity.profile: UserProfile` + `getProfileField(profile,key,fallback)`; `apps/web/src/hooks/useProfile.ts`: `useProfile()` (`useCustom GET /me/profile` or derived from `useGetIdentity`), `useUpdateProfile()` (`useCustomMutation PATCH/PUT + invalidate ["profile","me","auth","me"]`), `useExportProfile()`, `useDeleteAccount()` — all URLs relative to `/api/v1`, no raw `fetch` | M | `getProfileField({first_name:"A", custom_data:{x:1}}, "x")→1`; `getProfileField(p,"first_name")→"A"`; `useUpdateProfile` invalidates `GET /auth/me` cache |
| **D2. Profile settings page** | FR-11, FR-12 | `apps/web/src/pages/settings/ProfileSettingsPage.tsx` route `/settings/profile` (settings route, not Refine resource `create`), shadcn `Form` + `zod` (limits mirroring Pydantic), fields for each common col + `avatar_url` URL input (no uploader), key-value editor for `custom_data` (null→delete). `successNotification`, `errorNotification:false` when rendering `detail` | M | valid submit → `PATCH` → success toast + both caches invalidated; invalid `website_url` → inline `FormMessage`, no mutation; 422 `detail` appears once |
| **D3. Route + nav wiring** | FR-11, FR-12 | Register route in `apps/web/src/App.tsx` (add `"/settings/profile"` outside resources or as resource with `list: "/settings/profile"` per canonical), add settings link in header/avatar menu; ensure Vite proxy `/api/` still not capturing SPA refresh | S | hard refresh `/settings/profile` → 200 HTML not API 404; nav reachable from header |
| **D4. Export / delete UI** | FR-14, FR-15 | Buttons on settings page: "Export my data" → triggers `useExportProfile` and downloads `export-{id}.json`; "Delete account" → dialog with `confirm="DELETE"` + password input when `Identity` has password (derived), calls `DELETE /me`, clears tokens, redirects to `/login` | M | export click downloads valid JSON; delete with wrong pw shows error; delete with correct payload → 204, `localStorage` cleared, redirect to login, `GET /auth/me` fails |

**Deps:** A, B (APIs must exist). **Owner:** frontend. **Risks:** double-toast on 422 — assert single `FormMessage`/toast.

---

## Epic E — QA, Docs & Rollout (AD-7, Deferred items)

**Goal:** Ship with confidence and a non-bloated doc footprint. *Binds §14, §16, §6, Deferred.*

| Story | FRs | Spec | Size | Done when |
|---|---|---|---|---|
| **E1. Coverage & invariants** | all | Unit + e2e: A2 concurrency, B1 Merge Patch matrix, B2 404 guard, B4 secret redaction, B5 cascade+401, C1/C2 seams, `profile.updated` audit, `custom_data` bounds, redaction on public projection; frontend e2e: `ProfileSettingsPage` submit + error single-toast | M | `make api-test` + `npm run build` pass; coverage for new files ≥85% |
| **E2. Backfill verification** | FR-1 | Manual check script + migration test against DB with N legacy users → N profiles, idempotent rerun leaves count unchanged | XS | CI runs migration twice, asserts idempotent |
| **E3. Docs + rollout note** | FR-10, §14 | Update `docs/ARCHITECTURE.md` §3 domain model (add `UserProfile`), add `docs/providers/profile.md` (extension + promotion); release notes mention `GET /auth/me` additive field, `avatar_url` empty default, deferred upload | S | `grep` docs show new model; verified `make dev` → `GET /auth/me` smoke + `/me/export` smoke + throwaway delete in staging |
| **E4. Telemetry sanity (optional)** | SM-5/6 | Log `changed_fields` on profile mutations at INFO; ensure no `bio`/`custom_data` values at INFO — grep logs in test | XS | Log line contains `user_id`+`changed_fields`, does not contain test `bio` value |

**Deps:** all above. **Owner:** qa/docs. **Risks:** docs without code links — include `file:line_number` citations.

---

## Sequencing & dependencies

```
A (model+migration) ──▶ B (APIs+export/delete) ──┐
                                    │              ├─▶ E (qa/docs)
C (seam tests) ──────────────────────┘              │
D (frontend) ─── depends on B1/B4/B5 APIs ─────────┘
```

- **Phase 1 (1 day):** A1, A3 → unblock B.
- **Phase 2 (1–2 days):** B1–B3, B6 in parallel with D1.
- **Phase 3 (1 day):** B4, B5, D2–D4.
- **Phase 4 (0.5 day):** C1–C3, E1–E4.

Estimate **4–5 days** single engineer; 2–3 days with pair (API + web in parallel).

## Risks & mitigations (from Spine Deferred)

- **Avatar expectation:** UI copy makes clear `avatar_url` is a pasted URL, may be empty — no upload path. Mitigates user confusion.
- **Search pressure:** defer GIN/index; if a fork later needs `custom_data` filtering, they add an epic that introduces a read-model + index without touching this seam.
- **Per-field ACL:** not in v1 — if required later, would introduce a `field_visibility` map in `custom_data` or a new `profile_visibility` table behind `public_projection`.

## Acceptance checklist (maps to SMs)

- [ ] ≥90% of `users` have profiles after migration (backfill + lazy) — SM-1
- [ ] Merge Patch matrix (add/retain/null-delete) passes e2e — SM-2
- [ ] Seam tests (add column → PATCH → `getProfileField`) pass without helper edits — SM-3
- [ ] `GET /me/export` includes `profile` and excludes secrets; `DELETE /me` cascades + 401 after — SM-4
- [ ] p95 `GET /auth/me` (with JOIN) <150ms in dev pgserver
- [ ] Adding a new field <15min wall-clock via docs recipe — SM-6
- [ ] `npm run build` (tsc + vite) green on main and on seam branch

## Output contract for `bmad-build`

Each story above meets `bmad-build` AC-id requirements:
- **Given** authenticated user / co-member / non-co-member / OAuth user without password
- **When** invoking the named endpoint/hook
- **Then** status + payload shape + cascade/invalidation/audit observable

Next after plan: `bmad-create-epics-and-stories` can materialize these epics into `_bmad-output/implementation-artifacts/sprint-status.yaml` for tracker sync, or `bmad-build` can ingest this file directly.

