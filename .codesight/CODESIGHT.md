# saas-template — AI Context Map

> **Stack:** fastapi | sqlalchemy | react | typescript
> **Monorepo:** api, saas-template-web

> 37 routes | 13 models | 31 components | 53 lib files | 22 env vars | 2 middleware | 28% test coverage
> **Token savings:** this file is ~5,600 tokens. Without it, AI exploration would cost ~60,600 tokens. **Saves ~55,100 tokens per conversation.**
> **Last scanned:** 2026-08-24 18:49 — re-run after significant changes

---

# Routes

## CRUD Resources

- **``** GET | POST | GET/:id | PATCH/:id | DELETE/:id
- **`/global`** GET | GET/:id | PATCH/:id → Global

## Other Routes

- `GET` `/effective-permissions` params()
- `POST` `/register` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/login` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/refresh` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/logout` params() → in: RegisterRequest, out: TokenResponse [auth]
- `GET` `/me` params() → out: TokenResponse
- `POST` `/accept` params() → in: InvitationCreate [auth, db]
- `GET` `/mine` params()
- `POST` `/{invitation_id}/decline` params(invitation_id) → in: InvitationCreate
- `POST` `/global/{definition_id}/execute` params(definition_id)
- `GET` `/global/{definition_id}/runs` params(definition_id)
- `GET` `/runs/{run_id}` params(run_id)
- `GET` `/runs/{run_id}/logs` params(run_id)
- `POST` `/{definition_id}/execute` params(definition_id) [auth]
- `GET` `/{definition_id}/runs` params(definition_id) [auth]
- `GET` `/healthz` params()
- `GET` `/readyz` params()
- `GET` `/unread-count` params()
- `GET` `/permission-catalog` params()
- `GET` `/` params() ✓

---

# Schema

### ApiKey
- id: str (pk, default)
- workspace_id: str (index)
- name: String
- key_prefix: String
- key_hash: String (unique, index)
- permissions: JSON (default)
- created_by_user_id: str (index)
- last_used_at: DateTime (nullable)
- revoked_at: DateTime (nullable)

### AuditLogEntry
- id: str (pk, default)
- workspace_id: unknown (index, nullable)
- actor_user_id: unknown (nullable)
- resource_type: String
- resource_id: str
- action: String
- details: JSON (default)
- ip_address: String (nullable)

### Invitation
- id: str (pk, default)
- workspace_id: str (index)
- email: String
- role_id: str
- invited_by_user_id: str
- token: String (unique, index)
- status: String (default)
- expires_at: DateTime
- accepted_at: DateTime (nullable)

### Notification
- id: str (pk, default)
- user_id: str (index)
- workspace_id: str (index)
- type: String
- title: String
- body: String (nullable)
- payload: JSON (default)
- acknowledged_at: DateTime (nullable)

### JobDefinition
- id: str (pk, default)
- key: String (index)
- workspace_id: unknown (index, nullable)
- name: String
- description: Text (default)
- cron_schedule: String
- params_schema: JSON (default)
- params: JSON (default)
- enabled: bool (default)
- missed_policy: String (default)
- timeout_seconds: Integer (default)
- next_run_at: DateTime (nullable)
- last_run_at: DateTime (nullable)

### JobRun
- id: str (pk, default)
- definition_id: str (index)
- workspace_id: unknown (index, nullable)
- status: String (default, index)
- trigger: String (default)
- actor_user_id: unknown (index, nullable)
- params: JSON (default)
- scheduled_at: DateTime
- started_at: DateTime (nullable)
- finished_at: DateTime (nullable)
- duration_ms: Integer (nullable)
- error: Text (nullable)
- correlation_id: String (nullable)

### JobLogEntry
- id: str (pk, default)
- run_id: str (index)
- seq: Integer (default)
- ts: DateTime
- level: String (default)
- message: Text

### StoredSecret
- id: str (pk, default)
- workspace_id: str (index)
- secret_key: String (index)
- kind: String
- label: String (nullable)
- ciphertext: Text
- key_version: Integer
- meta: JSON (default)
- expires_at: DateTime (nullable)

### User
- id: str (pk, default)
- email: String (unique, index)
- password_hash: String (nullable)
- display_name: String
- avatar_url: String (nullable)
- is_active: Boolean (default)
- is_superuser: Boolean (default)
- last_login_at: DateTime (nullable)

### RefreshToken
- id: str (pk, default)
- user_id: str (index)
- token_hash: String (unique, index)
- expires_at: DateTime
- revoked_at: DateTime (nullable)

### Workspace
- id: str (pk, default)
- name: String
- slug: String (unique, index)
- description: String (nullable)
- created_by_user_id: str (index)

### Role
- id: str (pk, default)
- workspace_id: str (index)
- name: String
- description: String (nullable)
- permissions: JSON (default)
- system: Boolean (default)

### WorkspaceMember
- id: str (pk, default)
- workspace_id: str (index)
- user_id: str (index)
- role_id: str (index)
- status: String (default)

---

# Components

- **App** — `apps/web/src/App.tsx`
- **AppLayout** — `apps/web/src/components/AppLayout.tsx`
- **NotificationCenter** — `apps/web/src/components/NotificationCenter.tsx`
- **CreateButton** [client] — props: resource — `apps/web/src/components/refine-ui/buttons/create.tsx`
- **DeleteButton** [client] — props: resource, recordItemId — `apps/web/src/components/refine-ui/buttons/delete.tsx`
- **EditButton** [client] — props: resource, recordItemId — `apps/web/src/components/refine-ui/buttons/edit.tsx`
- **InputPassword** [client] — props: className — `apps/web/src/components/refine-ui/form/input-password.tsx`
- **PageHeader** [client] — props: resource, title, subtitle, actions, className, headerClassName — `apps/web/src/components/refine-ui/layout/page-header.tsx`
- **UndoableNotification** — props: message, description, undoableTimeout, cancelMutation, onClose — `apps/web/src/components/refine-ui/notification/undoable-notification.tsx`
- **ThemeProvider** [client] — props: defaultTheme, storageKey — `apps/web/src/components/refine-ui/theme/theme-provider.tsx`
- **ThemeSelect** [client] — `apps/web/src/components/refine-ui/theme/theme-select.tsx`
- **ThemeToggle** [client] — props: className — `apps/web/src/components/refine-ui/theme/theme-toggle.tsx`
- **CreateView** [client] — props: className — `apps/web/src/components/refine-ui/views/create-view.tsx`
- **ListView** [client] — props: className — `apps/web/src/components/refine-ui/views/list-view.tsx`
- **StatusBadge** — props: status — `apps/web/src/components/ui.tsx`
- **WorkspaceProvider** — `apps/web/src/contexts/WorkspaceContext.tsx`
- **MOBILE_BREAKPOINT** — `apps/web/src/hooks/use-mobile.tsx`
- **ApiKeyCreatePage** — `apps/web/src/pages/ApiKeyCreatePage.tsx`
- **ApiKeysPage** — `apps/web/src/pages/ApiKeysPage.tsx`
- **DashboardPage** — `apps/web/src/pages/DashboardPage.tsx`
- **InboxPage** — `apps/web/src/pages/InboxPage.tsx`
- **JobDetailPage** — `apps/web/src/pages/JobDetailPage.tsx`
- **JobRunPage** — `apps/web/src/pages/JobRunPage.tsx`
- **JobsPage** — `apps/web/src/pages/JobsPage.tsx`
- **LoginPage** — `apps/web/src/pages/LoginPage.tsx`
- **MembersPage** — `apps/web/src/pages/MembersPage.tsx`
- **NotificationsPage** — `apps/web/src/pages/NotificationsPage.tsx`
- **ReceivedInvitationsPage** — `apps/web/src/pages/ReceivedInvitationsPage.tsx`
- **RegisterPage** — `apps/web/src/pages/RegisterPage.tsx`
- **RolesPage** — `apps/web/src/pages/RolesPage.tsx`
- **WorkspaceCreatePage** — `apps/web/src/pages/WorkspaceCreatePage.tsx`

---

# Libraries

- `apps/api/alembic/env.py`
  - function run_migrations_offline: () -> None
  - function do_run_migrations: (connection) -> None
  - function run_migrations_online: () -> None
- `apps/api/alembic/versions/0001_initial.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0002_api_keys.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0003_audit_nullable_workspace.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0004_jobs.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/src/api/crud.py`
  - function parse_query: (request, *, max_limit) -> QuerySpec
  - function apply_query: (stmt, model, spec, *, sortable, filterable) -> Select
  - function run_list: (session, stmt, model, request, *, sortable, filterable) -> tuple[list[Any], int]
  - class QuerySpec
  - class InvalidQuery
- `apps/api/src/api/deps.py`
  - function get_container: (request)
  - function require_key_permission: (permission)
  - function require_permission: (permission)
  - class AuthPrincipal
- `apps/api/src/container.py` — class Container
- `apps/api/src/core/cache.py` — class TtlCache
- `apps/api/src/core/dates.py` — function ensure_utc: (value) -> datetime, function now_utc: () -> datetime
- `apps/api/src/core/permissions.py` — function permissions_for_role: (role_name) -> list[str]
- `apps/api/src/core/security/crypto.py` — class SecretCipher
- `apps/api/src/core/security/password.py` — class PasswordHasher
- `apps/api/src/core/security/tokens.py`
  - function create_access_token: (user_id, *, expires_minutes) -> str
  - function decode_access_token: (token) -> dict[str, Any]
  - class OpaqueToken
- `apps/api/src/db/base.py`
  - class StringUUID
  - class Base
  - class TimestampMixin
  - class StrEnum
- `apps/api/src/db/embedded.py`
  - function data_dir: () -> Path
  - function ensure_started: ()
  - function embedded_uri: () -> str
- `apps/api/src/db/session.py` — function get_db: () -> AsyncGenerator[AsyncSession, None]
- `apps/api/src/events/bus.py`
  - class EventMetadata
  - class EventEnvelope
  - class EventBus
  - class PublishError
  - class SubscriptionError
- `apps/api/src/events/factory.py` — function build_event_bus: () -> EventBus, class WorkflowRegistry
- `apps/api/src/events/inprocess.py` — class InProcessEventBus
- `apps/api/src/events/nats.py` — class NatsEventBus
- `apps/api/src/events/publisher.py`
  - function audit_payload: (*, workspace_id, resource_type, resource_id, action, actor_user_id, details, ip_address) -> dict
  - function publish_event: (bus, subject, payload, *, correlation_id, transient) -> None
  - function publish_audit: (bus, *, correlation_id, **kwargs) -> None
- `apps/api/src/events/subjects.py` — class EventBusDriver, class Subjects
- `apps/api/src/jobs/builtin.py`
  - function system_heartbeat: (ctx) -> None
  - function expire_stale_invitations: (ctx) -> None
  - function demo_global_daily_report: (ctx) -> None
- `apps/api/src/jobs/capture.py`
  - function run_log_collector: () -> RunLogCollector | None
  - function set_run_log_collector: (collector)
  - function reset_run_log_collector: (token) -> None
  - function install_run_capture: () -> None
  - function uninstall_run_capture: () -> None
  - class CapturedEntry
  - _...3 more_
- `apps/api/src/jobs/executor.py` — function execute_run: (run_id) -> None
- `apps/api/src/jobs/registry.py`
  - function validate_cron_schedule: (expr) -> None
  - function next_cron_occurrence: (expr, after) -> datetime
  - function validate_params: (schema, dict[str, Any]], values, Any]) -> dict[str, Any]
  - function default_params: (schema, dict[str, Any]]) -> dict[str, Any]
  - function register_builtin_jobs: () -> None
  - class ValidationError
  - _...4 more_
- `apps/api/src/jobs/scheduler.py` — class JobScheduler
- `apps/api/src/main.py` — function lifespan: (app), function root: () -> dict
- `apps/api/src/models/api_key.py` — class ApiKey
- `apps/api/src/models/audit.py` — class AuditLogEntry
- `apps/api/src/models/core.py` — class Invitation, class Notification
- `apps/api/src/models/jobs.py`
  - class JobScope
  - class JobRunStatus
  - class JobTrigger
  - class MissedJobPolicy
  - class JobDefinition
  - class JobRun
  - _...1 more_
- `apps/api/src/models/secret.py` — class StoredSecret
- `apps/api/src/models/workspace.py`
  - class User
  - class RefreshToken
  - class Workspace
  - class Role
  - class WorkspaceMember
- `apps/api/src/realtime/manager.py` — class ConnectionManager
- `apps/api/src/schemas/api.py`
  - class LoginRequest
  - class RegisterRequest
  - class TokenResponse
  - class RefreshRequest
  - class WorkspaceCreate
  - class WorkspaceUpdate
  - _...7 more_
- `apps/api/src/secrets/base.py` — class SecretRecord, class SecretStore
- `apps/api/src/secrets/db_store.py` — class DbSecretStore
- `apps/api/src/secrets/factory.py` — function build_secret_store: () -> SecretStore
- `apps/api/src/seed.py` — function main: () -> None
- `apps/api/src/services/api_keys.py`
  - class ApiKeyError
  - class ApiKeyForbidden
  - class ApiKeyNotFound
  - class ApiKeyService
- `apps/api/src/services/audit.py` — function audit_log_to_dict: (entry) -> dict[str, Any], class AuditService
- `apps/api/src/services/auth.py`
  - class AuthError
  - class TokenPair
  - class AuthService
- `apps/api/src/services/jobs.py`
  - function job_to_dict: (d) -> dict
  - function job_run_to_dict: (r, *, schema) -> dict
  - function job_log_to_dict: (e) -> dict
  - class JobError
  - class JobService
- `apps/api/src/services/notifications.py` — class NotificationService
- `apps/api/src/services/serializers.py`
  - function notification_to_dict: (n, *, workspace_name) -> dict
  - function user_to_dict: (u) -> dict
  - function workspace_to_dict: (w, *, role, permissions) -> dict
- `apps/api/src/services/workspaces.py`
  - class WorkspaceError
  - class WorkspaceForbidden
  - class WorkspaceConflict
  - class WorkspaceService
- `apps/api/src/settings.py` — class Settings
- `apps/api/src/workflows/__init__.py` — function build_workflows: (registry, bus, connection_manager, cipher) -> None
- `apps/web/src/lib/utils.ts` — function cn: (...inputs) => void, function oktaAdminConsoleFix: (value?) => string | null
- `apps/web/src/utils/permissions.ts` — function activeWorkspacePermissions: (identity?) => string[]
- `scripts/dev.py`
  - function main: () -> int
  - function kill_all: (procs, sig) -> None
  - function wait_all: (procs, timeout) -> None

---

# Config

## Environment Variables

- `ACCESS_TOKEN_EXPIRE_MINUTES` (has default) — apps/api/.env.example
- `APP_NAME` (has default) — apps/api/.env.example
- `CORS_ORIGINS` (has default) — apps/api/.env.example
- `DATABASE_URL` **required** — apps/api/tests/conftest.py
- `DEBUG` (has default) — apps/api/.env.example
- `DOCKER_HOST` (has default) — apps/api/tests/test_nats_integration.py
- `EMBEDDED_DB_DIR` (has default) — apps/api/.env
- `ENVIRONMENT` (has default) — apps/api/.env.example
- `EVENT_BUS_DRIVER` (has default) — apps/api/.env.example
- `FERNET_KEYS` (has default) — apps/api/.env.example
- `FRONTEND_URL` (has default) — apps/api/.env.example
- `JOBS_DEFAULT_TIMEOUT_SECONDS` (has default) — apps/api/.env.example
- `JOBS_RUN_RETENTION` (has default) — apps/api/.env.example
- `JOBS_SCHEDULER_TICK_SECONDS` (has default) — apps/api/.env.example
- `NATS_URL` (has default) — apps/api/.env.example
- `REFRESH_TOKEN_EXPIRE_DAYS` (has default) — apps/api/.env.example
- `SECRET_ENCRYPT_VERSION` (has default) — apps/api/.env.example
- `SECRET_KEY` (has default) — apps/api/.env.example
- `SECRET_STORE_DRIVER` (has default) — apps/api/.env.example
- `SUPERADMIN_EMAIL` **required** — apps/api/.env.example
- `VITE_API_URL` (has default) — apps/web/src/providers/dataProvider.ts
- `VITE_WS_URL` (has default) — apps/web/src/providers/liveProvider.ts

## Config Files

- `apps/api/.env.example`
- `apps/web/.env.example`
- `apps/web/tailwind.config.js`
- `apps/web/vite.config.ts`

---

# Middleware

## auth
- auth — `apps/api/src/services/auth.py`
- authProvider — `apps/web/src/providers/authProvider.ts`

---

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

---

# Test Coverage

> **28%** of routes and models are covered by tests
> 18 test files found

## Covered Routes

- GET:
- POST:
- GET:/

## Covered Models

- ApiKey
- AuditLogEntry
- Invitation
- Notification
- JobDefinition
- JobRun
- JobLogEntry
- StoredSecret
- User
- Workspace
- Role

---

# Git Hooks

> **Note for agents:** These hooks fire automatically on git operations and will block the operation if they fail.

## `pre-commit` — raw git hook

- **npx**: `npx codesight --wiki -o .codesight`
- **git**: `git add .codesight/`

_Source: .git/hooks/pre-commit_

---

_Generated by [codesight](https://github.com/Houseofmvps/codesight) — see your codebase clearly_