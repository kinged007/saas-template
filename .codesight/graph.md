# Dependency Graph

## Most Imported Files (change these carefully)

- `apps/api/src/db/session.py` — imported by **21** files
- `apps/api/src/models/workspace.py` — imported by **14** files
- `apps/web/src/types.ts` — imported by **13** files
- `apps/api/src/events/bus.py` — imported by **12** files
- `apps/api/src/settings.py` — imported by **11** files
- `apps/api/src/services/workspaces.py` — imported by **10** files
- `apps/api/src/models/core.py` — imported by **10** files
- `apps/api/src/api/deps.py` — imported by **9** files
- `apps/api/src/core/permissions.py` — imported by **9** files
- `apps/api/src/events/subjects.py` — imported by **9** files
- `apps/api/tests/conftest.py` — imported by **8** files
- `apps/api/src/db/base.py` — imported by **7** files
- `apps/api/src/models/api_key.py` — imported by **7** files
- `apps/api/src/services/auth.py` — imported by **7** files
- `apps/api/src/schemas/api.py` — imported by **7** files
- `apps/web/src/contexts/WorkspaceContext.tsx` — imported by **7** files
- `apps/api/src/api/crud.py` — imported by **6** files
- `apps/api/src/core/dates.py` — imported by **6** files
- `apps/web/src/components/ui.tsx` — imported by **6** files
- `apps/web/src/utils/storage.ts` — imported by **6** files

## Import Map (who imports what)

- `apps/api/src/db/session.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py` +16 more
- `apps/api/src/models/workspace.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py`, `apps/api/src/api/routes/notifications.py`, `apps/api/src/api/routes/roles.py` +9 more
- `apps/web/src/types.ts` ← `apps/web/src/components/AppLayout.tsx`, `apps/web/src/components/NotificationCenter.tsx`, `apps/web/src/contexts/WorkspaceContext.tsx`, `apps/web/src/pages/ApiKeyCreatePage.tsx`, `apps/web/src/pages/ApiKeysPage.tsx` +8 more
- `apps/api/src/events/bus.py` ← `apps/api/src/container.py`, `apps/api/src/events/factory.py`, `apps/api/src/events/inprocess.py`, `apps/api/src/events/nats.py`, `apps/api/src/events/publisher.py` +7 more
- `apps/api/src/settings.py` ← `apps/api/alembic/env.py`, `apps/api/src/container.py`, `apps/api/src/core/security/tokens.py`, `apps/api/src/db/session.py`, `apps/api/src/events/factory.py` +6 more
- `apps/api/src/services/workspaces.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py` +5 more
- `apps/api/src/models/core.py` ← `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/notifications.py`, `apps/api/src/models/__init__.py`, `apps/api/src/seed.py`, `apps/api/src/services/notifications.py` +5 more
- `apps/api/src/api/deps.py` ← `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py`, `apps/api/src/api/routes/notifications.py` +4 more
- `apps/api/src/core/permissions.py` ← `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py`, `apps/api/src/api/routes/notifications.py`, `apps/api/src/api/routes/roles.py` +4 more
- `apps/api/src/events/subjects.py` ← `apps/api/src/events/nats.py`, `apps/api/src/events/publisher.py`, `apps/api/src/services/api_keys.py`, `apps/api/src/services/notifications.py`, `apps/api/src/services/workspaces.py` +4 more
