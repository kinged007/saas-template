# Libraries

> **Navigation aid.** Library inventory extracted via AST. Read the source files listed here before modifying exported functions.

**53 library files** across 3 modules

## Api (50 files)

- `apps/api/src/schemas/api.py` — LoginRequest, RegisterRequest, TokenResponse, RefreshRequest, WorkspaceCreate, WorkspaceUpdate, …
- `apps/api/src/jobs/registry.py` — validate_cron_schedule, next_cron_occurrence, validate_params, default_params, register_builtin_jobs, ValidationError, …
- `apps/api/src/jobs/capture.py` — run_log_collector, set_run_log_collector, reset_run_log_collector, install_run_capture, uninstall_run_capture, CapturedEntry, …
- `apps/api/src/models/jobs.py` — JobScope, JobRunStatus, JobTrigger, MissedJobPolicy, JobDefinition, JobRun, …
- `apps/api/src/api/crud.py` — parse_query, apply_query, run_list, QuerySpec, InvalidQuery
- `apps/api/src/events/bus.py` — EventMetadata, EventEnvelope, EventBus, PublishError, SubscriptionError
- `apps/api/src/models/workspace.py` — User, RefreshToken, Workspace, Role, WorkspaceMember
- `apps/api/src/services/jobs.py` — job_to_dict, job_run_to_dict, job_log_to_dict, JobError, JobService
- `apps/api/src/api/deps.py` — get_container, require_key_permission, require_permission, AuthPrincipal
- `apps/api/src/db/base.py` — StringUUID, Base, TimestampMixin, StrEnum
- `apps/api/src/services/api_keys.py` — ApiKeyError, ApiKeyForbidden, ApiKeyNotFound, ApiKeyService
- `apps/api/src/services/workspaces.py` — WorkspaceError, WorkspaceForbidden, WorkspaceConflict, WorkspaceService
- `apps/api/alembic/env.py` — run_migrations_offline, do_run_migrations, run_migrations_online
- `apps/api/src/core/security/tokens.py` — create_access_token, decode_access_token, OpaqueToken
- `apps/api/src/db/embedded.py` — data_dir, ensure_started, embedded_uri
- `apps/api/src/events/publisher.py` — audit_payload, publish_event, publish_audit
- `apps/api/src/jobs/builtin.py` — system_heartbeat, expire_stale_invitations, demo_global_daily_report
- `apps/api/src/services/auth.py` — AuthError, TokenPair, AuthService
- `apps/api/src/services/serializers.py` — notification_to_dict, user_to_dict, workspace_to_dict
- `apps/api/alembic/versions/0001_initial.py` — upgrade, downgrade
- `apps/api/alembic/versions/0002_api_keys.py` — upgrade, downgrade
- `apps/api/alembic/versions/0003_audit_nullable_workspace.py` — upgrade, downgrade
- `apps/api/alembic/versions/0004_jobs.py` — upgrade, downgrade
- `apps/api/src/core/dates.py` — ensure_utc, now_utc
- `apps/api/src/events/factory.py` — build_event_bus, WorkflowRegistry
- _…and 25 more files_

## Web (2 files)

- `apps/web/src/lib/utils.ts` — cn, oktaAdminConsoleFix
- `apps/web/src/utils/permissions.ts` — activeWorkspacePermissions

## Scripts (1 files)

- `scripts/dev.py` — main, kill_all, wait_all

---
_Back to [overview.md](./overview.md)_