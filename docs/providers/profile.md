# UserProfile — Extension Seam

Dedicated `user_profiles` table 1:1 with `users` (`user_id` PK FK CASCADE). Stores 9 common fields + schemaless `custom_data JSON`.

## Model & Storage

- Table `user_profiles` (`apps/api/src/models/user_profile.py:1`, `apps/api/alembic/versions/0006_user_profiles.py:1`): `user_id` PK FK, 9 nullable columns, `custom_data JSON NOT NULL DEFAULT '{}'`, `created_at/updated_at` via `TimestampMixin`.
- Provisioned eagerly on `AuthService.register` / `upsert_oauth_user` (`apps/api/src/services/auth.py:48`) and lazily via `ProfileService.get_or_create` (`apps/api/src/services/profiles.py:1`) — concurrent inserts use `ON CONFLICT DO NOTHING` + re-select, no 500.
- `custom_data` Merge Patch (RFC 7396): `PATCH` shallow-merges, `null` deletes a key, omission retains; `PUT` replaces bag when `custom_data` supplied else leaves unchanged. Bounds 50 keys / 16 KiB via `apps/api/src/services/profile_helpers.py:1` (`merge_custom_data`, `validate_custom_data`).

## API Surface (all behind `get_current_user`)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/me/profile` | own profile, auto-creates |
| `PUT` | `/api/v1/me/profile` | common fields; `custom_data` replaced if supplied |
| `PATCH` | `/api/v1/me/profile` | partial; `custom_data` Merge-Patched |
| `GET` | `/api/v1/users/{id}/profile` | workspace-bounded (co-member or superuser else 404), redacted projection (`phone_number`, `date_of_birth`, `_private*` stripped) |
| `GET` | `/api/v1/auth/me` | always embeds `profile` (same shape) |
| `GET` | `/api/v1/me/export` (+ superuser `/users/{id}/export`) | synchronous bundle `{exported_at, user, profile, workspaces, counts}` `Content-Disposition: attachment`, secrets excluded |
| `DELETE` | `/api/v1/me` (+ superuser `/users/{id}`) | body `{confirm:"DELETE", password?}` — password required when `password_hash` exists; 204, cascade deletes tokens/members/profile, publishes `audit.entry.created` `user.deleted`, old token 401 |

Serializers `profile_to_dict` / `public_projection` in `apps/api/src/services/serializers.py:1`. Audit on `PUT/PATCH` publishes `resource_type=user_profile action=profile.updated details={changed_fields:[]}` (no PII values).

## Frontend

- `UserProfile` type + `getProfileField(profile,key,fallback?)` in `apps/web/src/types.ts:1` — column wins over `custom_data`, fallback `?? null`.
- `useProfile` / `useUpdateProfile` / `useExportProfile` / `useDeleteAccount` in `apps/web/src/hooks/useProfile.ts:1` — `useCustom` relative to `/api/v1`, invalidates `auth` + `data` caches.
- Settings page `apps/web/src/pages/settings/ProfileSettingsPage.tsx:1` — shadcn `Form` + `zodResolver`, 9 fields + `avatar_url` URL input + key-value `custom_data` editor (null deletes), `successNotification`, `errorNotification:false` rendering `detail` once.

## 3-Step Extension Recipe

Adding a first-class field (e.g. `years_of_experience`) requires only:

1. **Backend model** — add nullable column to `UserProfile` in `apps/api/src/models/user_profile.py`:
   ```python
   years_of_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
   ```
2. **Backend schema** — add optional field to both `ProfileRead` and `ProfileUpdate` in `apps/api/src/schemas/api.py`:
   ```python
   years_of_experience: int | None = Field(default=None)
   ```
   (`ProfileUpdate` already has `extra="forbid"` — unknown top-level keys are 422)
3. **Frontend type** — extend `UserProfile` in `apps/web/src/types.ts`:
   ```ts
   years_of_experience?: number | null;
   ```
4. **Migration** — generate Alembic migration (`down_revision="0006"`), no service or helper edits needed:
   ```bash
   alembic revision --autogenerate -m "add years_of_experience to user_profiles"
   ```

After migration, `PATCH /me/profile {years_of_experience:5}` succeeds and `getProfileField(profile,"years_of_experience")` resolves top-level-first without touching `ProfileService` or `getProfileField`.

## Promotion Path (custom_data → column)

When a `custom_data` key becomes hot, promote it to a column without losing data:

```sql
-- One-liner data migration (postgres jsonb, sqlite json)
UPDATE user_profiles SET years_of_experience = CAST(custom_data->>'years_of_experience' AS INTEGER)
WHERE json_extract(custom_data, '$.years_of_experience') IS NOT NULL;
-- For postgres jsonb: UPDATE user_profiles SET years_of_experience = (custom_data->>'years_of_experience')::int WHERE custom_data ? 'years_of_experience';
```

Service reads prefer column over JSON when both exist; stop writing to `custom_data.years_of_experience` after promotion (optionally clear it).

## Verification Checklist

- `alembic upgrade head` backfills legacy users idempotently; rerun leaves count unchanged.
- `GET /me/profile` and `GET /auth/me` return identical `profile` shape.
- `PATCH {"custom_data":{"a":1}}` then `{"b":2}` → `{"a":1,"b":2}`; `PATCH {"custom_data":{"a":null}}` deletes `a`.
- Unknown top-level `PATCH {"unknown_field":1}` → 422.
- Bounds: 17 KiB or 51 keys → 422 `custom_data exceeds limits`.
- Cross-user: co-member 200 redacted, non-co-member 404.
- Audit `profile.updated` has `changed_fields` without values.
- Export excludes `password_hash`; delete cascade 204 + 401 on old token.
- `npm run build --prefix apps/web` green.
