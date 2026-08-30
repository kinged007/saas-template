# Dependency Graph

## Most Imported Files (change these carefully)

- `apps/api/src/db/session.py` — imported by **33** files
- `apps/web/src/types.ts` — imported by **23** files
- `apps/api/src/models/workspace.py` — imported by **20** files
- `apps/api/src/events/bus.py` — imported by **16** files
- `apps/api/src/settings.py` — imported by **14** files
- `apps/api/src/api/deps.py` — imported by **13** files
- `apps/api/src/core/permissions.py` — imported by **13** files
- `apps/api/src/models/core.py` — imported by **13** files
- `apps/api/src/services/workspaces.py` — imported by **12** files
- `apps/api/src/core/dates.py` — imported by **12** files
- `apps/api/src/events/subjects.py` — imported by **12** files
- `apps/api/tests/conftest.py` — imported by **11** files
- `apps/api/src/db/base.py` — imported by **10** files
- `apps/api/src/models/api_key.py` — imported by **10** files
- `apps/api/src/schemas/api.py` — imported by **10** files
- `apps/api/src/api/crud.py` — imported by **9** files
- `apps/api/src/services/serializers.py` — imported by **8** files
- `apps/api/src/events/publisher.py` — imported by **8** files
- `apps/api/src/models/jobs.py` — imported by **8** files
- `apps/api/src/core/security/crypto.py` — imported by **8** files

## Import Map (who imports what)

- `apps/api/src/db/session.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/conversations.py` +28 more
- `apps/web/src/types.ts` ← `apps/web/src/components/AppLayout.tsx`, `apps/web/src/components/AppLayout.tsx`, `apps/web/src/components/NotificationCenter.tsx`, `apps/web/src/contexts/WorkspaceContext.tsx`, `apps/web/src/hooks/useProfile.ts` +18 more
- `apps/api/src/models/workspace.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py`, `apps/api/src/api/routes/notifications.py` +15 more
- `apps/api/src/events/bus.py` ← `apps/api/src/container.py`, `apps/api/src/events/factory.py`, `apps/api/src/events/inprocess.py`, `apps/api/src/events/nats.py`, `apps/api/src/events/publisher.py` +11 more
- `apps/api/src/settings.py` ← `apps/api/alembic/env.py`, `apps/api/src/container.py`, `apps/api/src/core/security/tokens.py`, `apps/api/src/db/session.py`, `apps/api/src/events/factory.py` +9 more
- `apps/api/src/api/deps.py` ← `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/conversations.py`, `apps/api/src/api/routes/invitations.py` +8 more
- `apps/api/src/core/permissions.py` ← `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/conversations.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/jobs.py` +8 more
- `apps/api/src/models/core.py` ← `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/notifications.py`, `apps/api/src/jobs/builtin.py`, `apps/api/src/models/__init__.py`, `apps/api/src/seed.py` +8 more
- `apps/api/src/services/workspaces.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/jobs.py` +7 more
- `apps/api/src/core/dates.py` ← `apps/api/src/api/routes/invitations.py`, `apps/api/src/jobs/builtin.py`, `apps/api/src/jobs/executor.py`, `apps/api/src/seed.py`, `apps/api/src/services/api_keys.py` +7 more
