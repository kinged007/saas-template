# Addendum — Extendable User Profiles

## Source Inputs

- User prompt (this session): "introduce a new model schema for user profiles, these are seperate to the existing users table, but are directly linked to it obviously. The user profile model should contain common profile fields, and then a json field where more metadata may be stored for that user profile. as a template repo, the profile may be extended by developers for different projects, so our model schema, user classes in both backend and frontend should be easily extendable and flexible to fetch any new field they introduce, or a field from the json custom parameters easily."
- Codebase grounding: `apps/api/src/models/workspace.py:11` (User), `apps/api/src/db/base.py:50` (TimestampMixin), `apps/api/src/schemas/api.py:1`, `apps/web/src/types.ts:13`, `docs/ARCHITECTURE.md` §3-4, `apps/api/src/api/routes/auth.py:93` (`GET /auth/me`).

## Technical How (deferred from PRD §4)

- **Model file:** `apps/api/src/models/profile.py` — `class UserProfile(Base, TimestampMixin)` with `user_id: Mapped[str] = mapped_column(StringUUID(), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)` as both FK and unique index (or PK). Follow naming conventions in `apps/api/src/db/base.py:39`.
- **Alembic:** single revision `add_user_profiles` creating table + GIN note (“no GIN in v1”). Backfill: `INSERT INTO user_profiles (id, user_id, custom_data) SELECT gen_random_uuid(), id, '{}' FROM users WHERE id NOT IN (SELECT user_id FROM user_profiles)` using `uuid4()` via SA `StringUUID` default — use async session pattern from `apps/api/src/seed.py:1` if needed.
- **Pydantic v2:** use `ConfigDict(extra="forbid")` on `ProfileUpdate` top-level; `custom_data` typed `dict[str, Any]` validated by size helper. Serialization: backend `profile_to_dict` mirrors `apps/api/src/services/serializers.py:30` `user_to_dict` shape, merging via accessor when `?flatten_custom=true`.
- **Service:** `apps/api/src/services/profiles.py::ProfileService` with `get_or_create(session, user_id) -> UserProfile` using `select` + `INSERT ... ON CONFLICT DO NOTHING` via `sqlalchemy.dialects.postgresql.insert` fallback for SQLite (plain select+try). Methods: `update(user_id, data: ProfileUpdate) -> ProfileRead` with merge semantics described in PRD.
- **Routes:** `apps/api/src/api/routes/profiles.py` registered in `apps/api/src/main.py:12` alongside `auth`, `workspaces`. Deps `get_current_user`, optional `X-Workspace-ID` for cross-user read check (reuses `WorkspaceService.list_workspaces` or direct `select WorkspaceMember`).
- **Frontend helpers:** `apps/web/src/types.ts:202` — append `UserProfile` below `JobLogEntry`; add `export const getProfileField = (p, k, fb?) => (k in p && p[k]!=null ? p[k] : p.custom_data?.[k] ?? fb)` and `export function useProfile() { return useCustom<UserProfile>({url: "/me/profile", method: "get"}) }`. Keep `queryClient.ts` invalidation keys `["profile","me"]`.
- **Zod schema** on `/settings/profile` page mirrors Pydantic limits (100/100/1000/etc.) so `PUT` vs `PATCH` stays consistent.

## Options Considered

| Option | Why considered | Why rejected/deferred |
|---|---|---|
| Single-table inheritance (add JSON column directly on `users`) | Simpler migration | Rejected — pollutes `users` hot path, breaks template extension contract, and `users` is already high-blast-radius (13 importers). Separate table isolates profile churn. |
| EAV table (`profile_attributes`) | Most flexible | Rejected — unbounded row growth, harder to audit, and template consumers expect column semantics for hot keys. JSON bag is the pragmatic middle. |
| Per-workspace profiles (`workspace_member_profiles`) | Requested in some forks | Deferred to v2; global profile covers template common case, scoping key via `custom_data["workspace_overrides"]` is an interim seam. |
| GraphQL / sparse fieldset with JSONPath | Fine-grained fetch | Deferred; plain `fields=` csv + accessor covers v1 without adding query language. |

## Extension Recipe (to be copied to docs/providers/profile.md)

1. Backend: add `foo: Mapped[str | None] = mapped_column(String(100), nullable=True)` to `UserProfile`, add `foo: str | None = Field(default=None, max_length=100)` to `ProfileRead/Update`, `alembic revision --autogenerate -m "add foo to user_profiles" && alembic upgrade head`.
2. Frontend: add `foo?: string | null` to `UserProfile` in `apps/web/src/types.ts`, optionally add `<FormField name="foo">` to `/settings/profile`.
3. Verify: `PATCH /me/profile {foo:"bar"}` → `getProfileField(p,"foo")=="bar"`; `npm run build` passes.
4. Promotion: for key `foo` previously in `custom_data`, migration does `UPDATE user_profiles SET foo=custom_data->>'foo' WHERE custom_data ? 'foo'`.

## Risks & Mitigations

- **PII leakage via `custom_data`:** arbitrary keys may hold sensitive values. Mitigated by default private-prefix filter and serializer redaction for cross-user reads; docs warn to treat `custom_data` values as PII.
- **Concurrent creation race:** mitigated by unique constraint + retry.
- **Frontend type drift:** `UserProfile & Record<string, unknown>` intersection could hide typos. Mitigated by keeping `extra="forbid"` on inbound payloads and by preferring `getProfileField` over direct index access in shared components.

## Out-of-scope rationale

Avatar, search, realtime, field-level RBAC, and bulk ops are intentionally deferred to keep v1's blast radius minimal (one model, one service, two routes, one page) and to avoid coupling to file storage, search index, or permission matrix rewrites before the core seam is proven.
