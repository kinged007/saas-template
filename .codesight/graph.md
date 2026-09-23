# Dependency Graph

## Most Imported Files (change these carefully)

- `apps/api/src/db/session.py` — imported by **44** files
- `apps/api/src/settings.py` — imported by **32** files
- `apps/api/src/models/workspace.py` — imported by **30** files
- `apps/web/src/types.ts` — imported by **27** files
- `apps/api/tests/conftest.py` — imported by **23** files
- `apps/api/src/models/core.py` — imported by **19** files
- `apps/api/src/events/bus.py` — imported by **19** files
- `apps/api/src/core/dates.py` — imported by **18** files
- `apps/api/src/api/deps.py` — imported by **16** files
- `apps/api/src/core/permissions.py` — imported by **16** files
- `apps/api/src/db/base.py` — imported by **14** files
- `apps/api/src/services/workspaces.py` — imported by **14** files
- `apps/api/src/events/subjects.py` — imported by **14** files
- `apps/web/src/hooks/useWorkspaceQuery.ts` — imported by **14** files
- `apps/api/src/models/jobs.py` — imported by **13** files
- `apps/api/src/models/api_key.py` — imported by **12** files
- `apps/api/src/events/publisher.py` — imported by **12** files
- `apps/api/src/schemas/api.py` — imported by **12** files
- `apps/api/src/api/crud.py` — imported by **11** files
- `apps/api/src/models/audit.py` — imported by **11** files

## Import Map (who imports what)

- `apps/api/src/db/session.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/admin.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/auth.py` +39 more
- `apps/api/src/settings.py` ← `apps/api/alembic/env.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/oauth.py`, `apps/api/src/container.py`, `apps/api/src/core/security/ratelimit.py` +27 more
- `apps/api/src/models/workspace.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/admin.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py` +25 more
- `apps/web/src/types.ts` ← `apps/web/src/components/AppLayout.tsx`, `apps/web/src/components/AppLayout.tsx`, `apps/web/src/components/NotificationCenter.tsx`, `apps/web/src/contexts/WorkspaceContext.tsx`, `apps/web/src/hooks/useNotificationPreferences.ts` +22 more
- `apps/api/tests/conftest.py` ← `apps/api/tests/test_admin.py`, `apps/api/tests/test_api_key_security.py`, `apps/api/tests/test_api_keys.py`, `apps/api/tests/test_api_versioning_quotas.py`, `apps/api/tests/test_audit_workflow.py` +18 more
- `apps/api/src/models/core.py` ← `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/notifications.py`, `apps/api/src/db/cascade.py`, `apps/api/src/jobs/builtin.py`, `apps/api/src/models/__init__.py` +14 more
- `apps/api/src/events/bus.py` ← `apps/api/src/container.py`, `apps/api/src/events/factory.py`, `apps/api/src/events/inprocess.py`, `apps/api/src/events/nats.py`, `apps/api/src/events/publisher.py` +14 more
- `apps/api/src/core/dates.py` ← `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/jobs/builtin.py`, `apps/api/src/jobs/executor.py`, `apps/api/src/seed.py` +13 more
- `apps/api/src/api/deps.py` ← `apps/api/src/api/routes/admin.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/conversations.py` +11 more
- `apps/api/src/core/permissions.py` ← `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/conversations.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/jobs.py` +11 more
