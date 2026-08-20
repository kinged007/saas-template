# Dependency Graph

## Most Imported Files (change these carefully)

- `apps/api/src/db/session.py` — imported by **16** files
- `apps/api/src/models/workspace.py` — imported by **12** files
- `apps/web/src/types.ts` — imported by **12** files
- `apps/api/src/settings.py` — imported by **9** files
- `apps/api/src/services/workspaces.py` — imported by **9** files
- `apps/api/src/api/deps.py` — imported by **9** files
- `apps/api/src/models/core.py` — imported by **8** files
- `apps/api/src/db/base.py` — imported by **7** files
- `apps/api/src/core/permissions.py` — imported by **7** files
- `apps/api/src/schemas/api.py` — imported by **7** files
- `apps/api/src/events/bus.py` — imported by **7** files
- `apps/web/src/contexts/WorkspaceContext.tsx` — imported by **7** files
- `apps/api/src/api/crud.py` — imported by **6** files
- `apps/api/src/core/dates.py` — imported by **6** files
- `apps/web/src/components/ui.tsx` — imported by **6** files
- `apps/web/src/utils/storage.ts` — imported by **6** files
- `apps/api/src/models/api_key.py` — imported by **5** files
- `apps/api/src/services/auth.py` — imported by **5** files
- `apps/api/src/services/serializers.py` — imported by **5** files
- `apps/api/src/events/subjects.py` — imported by **5** files

## Import Map (who imports what)

- `apps/api/src/db/session.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py` +11 more
- `apps/api/src/models/workspace.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py`, `apps/api/src/api/routes/notifications.py`, `apps/api/src/api/routes/roles.py` +7 more
- `apps/web/src/types.ts` ← `apps/web/src/components/AppLayout.tsx`, `apps/web/src/components/NotificationCenter.tsx`, `apps/web/src/contexts/WorkspaceContext.tsx`, `apps/web/src/pages/ApiKeysPage.tsx`, `apps/web/src/pages/InboxPage.tsx` +7 more
- `apps/api/src/settings.py` ← `apps/api/alembic/env.py`, `apps/api/src/container.py`, `apps/api/src/core/security/tokens.py`, `apps/api/src/db/session.py`, `apps/api/src/events/factory.py` +4 more
- `apps/api/src/services/workspaces.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py` +4 more
- `apps/api/src/api/deps.py` ← `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py`, `apps/api/src/api/routes/notifications.py` +4 more
- `apps/api/src/models/core.py` ← `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/notifications.py`, `apps/api/src/models/__init__.py`, `apps/api/src/seed.py`, `apps/api/src/services/notifications.py` +3 more
- `apps/api/src/db/base.py` ← `apps/api/alembic/env.py`, `apps/api/src/models/api_key.py`, `apps/api/src/models/audit.py`, `apps/api/src/models/core.py`, `apps/api/src/models/secret.py` +2 more
- `apps/api/src/core/permissions.py` ← `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py`, `apps/api/src/api/routes/roles.py`, `apps/api/src/api/routes/workspaces.py` +2 more
- `apps/api/src/schemas/api.py` ← `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py`, `apps/api/src/api/routes/notifications.py` +2 more
