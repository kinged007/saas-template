# Dependency Graph

## Most Imported Files (change these carefully)

- `apps/api/src/db/session.py` — imported by **28** files
- `apps/web/src/types.ts` — imported by **16** files
- `apps/api/src/models/workspace.py` — imported by **15** files
- `apps/api/src/settings.py` — imported by **14** files
- `apps/api/src/events/bus.py` — imported by **13** files
- `apps/api/src/services/workspaces.py` — imported by **11** files
- `apps/api/src/core/permissions.py` — imported by **11** files
- `apps/api/src/core/dates.py` — imported by **11** files
- `apps/api/src/models/core.py` — imported by **11** files
- `apps/api/src/events/subjects.py` — imported by **11** files
- `apps/api/src/api/deps.py` — imported by **10** files
- `apps/api/tests/conftest.py` — imported by **10** files
- `apps/api/src/db/base.py` — imported by **8** files
- `apps/api/src/schemas/api.py` — imported by **8** files
- `apps/api/src/core/security/crypto.py` — imported by **8** files
- `apps/api/src/models/api_key.py` — imported by **7** files
- `apps/api/src/services/auth.py` — imported by **7** files
- `apps/api/src/api/crud.py` — imported by **7** files
- `apps/api/src/models/jobs.py` — imported by **7** files
- `apps/web/src/contexts/WorkspaceContext.tsx` — imported by **7** files

## Import Map (who imports what)

- `apps/api/src/db/session.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/jobs.py` +23 more
- `apps/web/src/types.ts` ← `apps/web/src/components/AppLayout.tsx`, `apps/web/src/components/NotificationCenter.tsx`, `apps/web/src/contexts/WorkspaceContext.tsx`, `apps/web/src/pages/ApiKeyCreatePage.tsx`, `apps/web/src/pages/ApiKeysPage.tsx` +11 more
- `apps/api/src/models/workspace.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py`, `apps/api/src/api/routes/notifications.py`, `apps/api/src/api/routes/roles.py` +10 more
- `apps/api/src/settings.py` ← `apps/api/alembic/env.py`, `apps/api/src/container.py`, `apps/api/src/core/security/tokens.py`, `apps/api/src/db/session.py`, `apps/api/src/events/factory.py` +9 more
- `apps/api/src/events/bus.py` ← `apps/api/src/container.py`, `apps/api/src/events/factory.py`, `apps/api/src/events/inprocess.py`, `apps/api/src/events/nats.py`, `apps/api/src/events/publisher.py` +8 more
- `apps/api/src/services/workspaces.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/jobs.py` +6 more
- `apps/api/src/core/permissions.py` ← `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/jobs.py`, `apps/api/src/api/routes/members.py`, `apps/api/src/api/routes/notifications.py` +6 more
- `apps/api/src/core/dates.py` ← `apps/api/src/api/routes/invitations.py`, `apps/api/src/jobs/builtin.py`, `apps/api/src/jobs/executor.py`, `apps/api/src/seed.py`, `apps/api/src/services/api_keys.py` +6 more
- `apps/api/src/models/core.py` ← `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/notifications.py`, `apps/api/src/jobs/builtin.py`, `apps/api/src/models/__init__.py`, `apps/api/src/seed.py` +6 more
- `apps/api/src/events/subjects.py` ← `apps/api/src/events/nats.py`, `apps/api/src/events/publisher.py`, `apps/api/src/services/api_keys.py`, `apps/api/src/services/jobs.py`, `apps/api/src/services/notifications.py` +6 more
