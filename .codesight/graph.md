# Dependency Graph

## Most Imported Files (change these carefully)

- `apps/api/src/db/session.py` — imported by **66** files
- `apps/api/src/models/workspace.py` — imported by **47** files
- `apps/api/src/settings.py` — imported by **42** files
- `apps/api/tests/conftest.py` — imported by **38** files
- `apps/web/src/types.ts` — imported by **38** files
- `apps/api/src/core/dates.py` — imported by **35** files
- `apps/web/e2e/mock-api.ts` — imported by **32** files
- `apps/web/e2e/fixtures.ts` — imported by **31** files
- `apps/api/src/models/core.py` — imported by **29** files
- `apps/api/src/events/bus.py` — imported by **29** files
- `apps/api/src/core/permissions.py` — imported by **23** files
- `apps/api/src/events/subjects.py` — imported by **23** files
- `apps/api/src/services/workspaces.py` — imported by **20** files
- `apps/api/src/models/api_key.py` — imported by **19** files
- `apps/api/src/services/auth.py` — imported by **18** files
- `apps/api/src/api/deps.py` — imported by **17** files
- `apps/api/src/models/audit.py` — imported by **17** files
- `apps/api/src/db/base.py` — imported by **16** files
- `apps/api/src/models/jobs.py` — imported by **16** files
- `apps/web/src/hooks/useWorkspaceQuery.ts` — imported by **15** files

## Import Map (who imports what)

- `apps/api/src/db/session.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/admin.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/auth.py` +61 more
- `apps/api/src/models/workspace.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/admin.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/invitations.py` +42 more
- `apps/api/src/settings.py` ← `apps/api/alembic/env.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/oauth.py`, `apps/api/src/container.py`, `apps/api/src/core/security/cookies.py` +37 more
- `apps/api/tests/conftest.py` ← `apps/api/tests/test_admin.py`, `apps/api/tests/test_api_key_expiry.py`, `apps/api/tests/test_api_key_quota_window.py`, `apps/api/tests/test_api_key_security.py`, `apps/api/tests/test_api_keys.py` +33 more
- `apps/web/src/types.ts` ← `apps/web/e2e/mock-api.ts`, `apps/web/e2e/mock-api.typecheck.ts`, `apps/web/src/components/AppLayout.tsx`, `apps/web/src/components/AppLayout.tsx`, `apps/web/src/components/NotificationCenter.tsx` +33 more
- `apps/api/src/core/dates.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/admin.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/auth.py` +30 more
- `apps/web/e2e/mock-api.ts` ← `apps/web/e2e/api-key-copy.spec.ts`, `apps/web/e2e/audit-log-refusal.spec.ts`, `apps/web/e2e/copy-button.spec.ts`, `apps/web/e2e/danger-zone.spec.ts`, `apps/web/e2e/dashboard-a11y.spec.ts` +27 more
- `apps/web/e2e/fixtures.ts` ← `apps/web/e2e/api-key-copy.spec.ts`, `apps/web/e2e/audit-log-refusal.spec.ts`, `apps/web/e2e/copy-button.spec.ts`, `apps/web/e2e/danger-zone.spec.ts`, `apps/web/e2e/dashboard-a11y.spec.ts` +26 more
- `apps/api/src/models/core.py` ← `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/notifications.py`, `apps/api/src/db/cascade.py`, `apps/api/src/jobs/builtin.py`, `apps/api/src/models/__init__.py` +24 more
- `apps/api/src/events/bus.py` ← `apps/api/src/container.py`, `apps/api/src/events/factory.py`, `apps/api/src/events/inprocess.py`, `apps/api/src/events/nats.py`, `apps/api/src/events/publisher.py` +24 more
