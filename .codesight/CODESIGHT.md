# saas-template — AI Context Map

> **Stack:** fastapi | sqlalchemy | react | typescript
> **Monorepo:** api, saas-template-web

> 94 routes | 23 models | 61 components | 99 lib files | 35 env vars | 3 middleware | 21% test coverage
> **Token savings:** this file is ~10,900 tokens. Without it, AI exploration would cost ~117,800 tokens. **Saves ~106,900 tokens per conversation.**
> **Last scanned:** 2026-09-23 16:03 — re-run after significant changes

---

# Routes

## CRUD Resources

- **`/users`** GET | GET/:id | PATCH/:id | DELETE/:id → User
- **``** GET | POST | GET/:id | PATCH/:id | DELETE/:id
- **`/sessions`** GET | GET/:id | DELETE/:id → Session
- **`/global`** GET | GET/:id | PATCH/:id → Global
- **`/subscriptions`** GET | POST | GET/:id | PATCH/:id | DELETE/:id → Subscription

## Other Routes

- `GET` `/workspaces` params() [db]
- `PATCH` `/workspaces/{workspace_id}/flags` params(workspace_id)
- `GET` `/audit` params() [db]
- `GET` `/effective-permissions` params()
- `GET` `/config` params() → out: TokenResponse [auth]
- `POST` `/register` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/forgot-password` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/reset-password` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/verify-email` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/resend-verification` params() → in: RegisterRequest, out: TokenResponse [auth, email]
- `POST` `/login` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/refresh` params() → in: RegisterRequest, out: TokenResponse [auth]
- `GET` `/2fa/status` params() → out: TokenResponse
- `POST` `/2fa/setup` params() → in: RegisterRequest, out: TokenResponse
- `POST` `/2fa/enable` params() → in: RegisterRequest, out: TokenResponse
- `POST` `/2fa/disable` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/2fa/backup-codes` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/2fa/login` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/logout` params() → in: RegisterRequest, out: TokenResponse [auth]
- `GET` `/me` params() → out: TokenResponse
- `GET` `/unread-count` params() → in: st
- `PATCH` `/{conversation_id}/read` params(conversation_id)
- `PATCH` `/{conversation_id}/unread` params(conversation_id)
- `PATCH` `/{conversation_id}/archive` params(conversation_id)
- `GET` `/{conversation_id}/messages` params(conversation_id) → in: st
- `POST` `/{conversation_id}/messages` params(conversation_id) → in: ConversationCreate
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
- `GET` `/metrics` params()
- `GET` `/readyz` params()
- `GET` `/preferences` params()
- `PUT` `/preferences` params() → in: NotificationPreferencesUpdate
- `GET` `/unsubscribe` params() [auth]
- `PATCH` `/read-all` params()
- `GET` `/{provider_id}/authorize` params(provider_id) [auth, cache]
- `GET` `/{provider_id}/callback` params(provider_id) [auth, cache]
- `POST` `/token` params() → in: OAuthTokenRequest [auth, db, cache]
- `GET` `/me/profile` params() → in: Use
- `PUT` `/me/profile` params() → in: ProfileUpdate [db]
- `PATCH` `/me/profile` params() → in: ProfileUpdate [db]
- `GET` `/users/{user_id}/profile` params(user_id) → in: Use
- `GET` `/me/export` params() → in: Use
- `GET` `/users/{user_id}/export` params(user_id) → in: Use
- `DELETE` `/me` params() → in: DeleteMeRequest [db]
- `GET` `/permission-catalog` params()
- `GET` `/events` params() [webhook]
- `POST` `/subscriptions/{subscription_id}/rotate-secret` params(subscription_id) → in: WebhookSubscriptionCreate [webhook]
- `GET` `/deliveries` params() [db, webhook]
- `GET` `/subscriptions/{subscription_id}/deliveries` params(subscription_id) [db, webhook]
- `GET` `/deliveries/{delivery_id}` params(delivery_id) [webhook]
- `POST` `/deliveries/{delivery_id}/redeliver` params(delivery_id) → in: WebhookSubscriptionCreate [webhook]
- `GET` `/search` params() → out: list
- `GET` `/export` params() → out: list
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
- usage_count: Integer (default)
- usage_quota: Integer (nullable)

### AuditLogEntry
- id: str (pk, default)
- workspace_id: unknown (index, nullable)
- actor_user_id: unknown (nullable)
- resource_type: String
- resource_id: str
- action: String
- details: JSON (default)
- ip_address: String (nullable)

### Conversation
- id: str (pk, default)
- workspace_id: str (index)
- created_by_user_id: str (index)
- title: String (nullable)
- last_message_at: DateTime (nullable, index)
- last_message_preview: String (nullable)

### ConversationParticipant
- id: str (pk, default)
- conversation_id: str (index)
- participant_type: String (default, index)
- participant_id: str (index)
- user_id: unknown (nullable, index)
- agent_id: unknown (nullable, index)
- joined_at: DateTime
- last_read_at: DateTime (nullable)
- last_read_message_id: unknown (nullable)
- archived_at: DateTime (nullable)

### Message
- id: str (pk, default)
- conversation_id: str (index)
- sender_type: String (default)
- sender_id: str (index)
- sender_user_id: unknown (nullable, index)
- sender_agent_id: unknown (nullable)
- body: Text
- body_html: Text (nullable)

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

### NotificationPreference
- id: str (pk, default)
- user_id: str (index)
- type: String
- channel: String (default)
- digest_enabled: Boolean (default)
- unsubscribe_token: String (index, nullable)

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

### OAuthAccount
- id: str (pk, default)
- user_id: str (fk, index)
- provider: String
- subject: String

### StoredSecret
- id: str (pk, default)
- workspace_id: str (index)
- secret_key: String (index)
- kind: String
- label: String (nullable)
- ciphertext: Text
- key_version: Integer
- meta: JSON (nullable, default)
- expires_at: DateTime (nullable)

### UserTotpCredential
- user_id: str (fk, pk)
- secret_ciphertext: Text
- last_counter: Integer (nullable)
- backup_codes: JSON (default)

### UserProfile
- user_id: str (fk, pk)
- first_name: String (nullable)
- last_name: String (nullable)
- bio: String (nullable)
- phone_number: String (nullable)
- timezone: String (nullable)
- locale: String (nullable)
- date_of_birth: Date (nullable)
- website_url: String (nullable)
- location: String (nullable)
- custom_data: JSON (default)

### WebhookSubscription
- id: str (pk, default)
- workspace_id: str (index)
- url: String
- events: JSON (default)
- active: Boolean (default)
- created_by_user_id: unknown (nullable)

### WebhookDelivery
- id: str (pk, default)
- subscription_id: str (index)
- workspace_id: str (index)
- event_type: String
- subject: String
- payload: JSON (default)
- status: String (default, index)
- attempt_count: Integer (default)
- next_retry_at: DateTime (nullable)
- last_attempt_at: DateTime (nullable)
- response_status: Integer (nullable)
- error: Text (nullable)
- event_id: String (nullable)
- correlation_id: String (nullable)

### User
- id: str (pk, default)
- email: String (unique, index)
- password_hash: String (nullable)
- display_name: String
- avatar_url: String (nullable)
- is_active: Boolean (default)
- is_superuser: Boolean (default)
- last_login_at: DateTime (nullable)
- email_verified_at: DateTime (nullable)
- totp_enabled: Boolean (default)

### AuthToken
- id: str (pk, default)
- user_id: str (index)
- purpose: String
- token_hash: String (unique, index)
- expires_at: DateTime
- consumed_at: DateTime (nullable)

### RefreshToken
- id: str (pk, default)
- user_id: str (index)
- token_hash: String (unique, index)
- expires_at: DateTime
- revoked_at: DateTime (nullable)
- ip_address: String (nullable)
- user_agent: String (nullable)

### Workspace
- id: str (pk, default)
- name: String
- slug: String (unique, index)
- description: String (nullable)
- created_by_user_id: str (index)
- flags: JSON (default)

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
- **AuditLogTable** — props: resource, searchPlaceholder, searchEnabled, showWorkspace — `apps/web/src/components/AuditLogTable.tsx`
- **SsoButtons** — props: providers, disabled — `apps/web/src/components/AuthConfig.tsx`
- **NotificationCenter** — `apps/web/src/components/NotificationCenter.tsx`
- **UserProfileDialog** — props: userId, open, onOpenChange, fallback — `apps/web/src/components/UserProfileDialog.tsx`
- **WorkspaceExportCard** — `apps/web/src/components/WorkspaceExportCard.tsx`
- **WorkspaceSearch** — `apps/web/src/components/WorkspaceSearch.tsx`
- **ComposeDialog** — props: open, onOpenChange, onCreated — `apps/web/src/components/inbox/ComposeDialog.tsx`
- **TiptapEditor** — props: value, onChange, placeholder, className, minHeight — `apps/web/src/components/inbox/TiptapEditor.tsx`
- **CreateButton** [client] — props: resource — `apps/web/src/components/refine-ui/buttons/create.tsx`
- **DeleteButton** [client] — props: resource, recordItemId — `apps/web/src/components/refine-ui/buttons/delete.tsx`
- **EditButton** [client] — props: resource, recordItemId — `apps/web/src/components/refine-ui/buttons/edit.tsx`
- **InputPassword** [client] — props: className — `apps/web/src/components/refine-ui/form/input-password.tsx`
- **PageHeader** [client] — props: resource, title, subtitle, actions, className, headerClassName — `apps/web/src/components/refine-ui/layout/page-header.tsx`
- **TabbedPageHeader** [client] — props: resource, title, subtitle, actions, tabs, className, headerClassName — `apps/web/src/components/refine-ui/layout/tabbed-page-header.tsx`
- **UndoableNotification** — props: message, description, undoableTimeout, cancelMutation, onClose — `apps/web/src/components/refine-ui/notification/undoable-notification.tsx`
- **ThemeProvider** [client] — props: defaultTheme, storageKey — `apps/web/src/components/refine-ui/theme/theme-provider.tsx`
- **ThemeSelect** [client] — `apps/web/src/components/refine-ui/theme/theme-select.tsx`
- **ThemeToggle** [client] — props: className — `apps/web/src/components/refine-ui/theme/theme-toggle.tsx`
- **CreateView** [client] — props: className — `apps/web/src/components/refine-ui/views/create-view.tsx`
- **ListView** [client] — props: className — `apps/web/src/components/refine-ui/views/list-view.tsx`
- **StatusBadge** — props: status — `apps/web/src/components/ui.tsx`
- **WorkspaceProvider** — `apps/web/src/contexts/WorkspaceContext.tsx`
- **MOBILE_BREAKPOINT** — `apps/web/src/hooks/use-mobile.tsx`
- **LinkBase** — props: href, className — `apps/web/src/lib/markdown.tsx`
- **ApiKeyCreatePage** — `apps/web/src/pages/ApiKeyCreatePage.tsx`
- **ApiKeysPage** — `apps/web/src/pages/ApiKeysPage.tsx`
- **DashboardPage** — `apps/web/src/pages/DashboardPage.tsx`
- **ForgotPasswordPage** — `apps/web/src/pages/ForgotPasswordPage.tsx`
- **InboxPage** — `apps/web/src/pages/InboxPage.tsx`
- **JobDetailPage** — `apps/web/src/pages/JobDetailPage.tsx`
- **JobRunPage** — `apps/web/src/pages/JobRunPage.tsx`
- **JobsPage** — `apps/web/src/pages/JobsPage.tsx`
- **LoginPage** — `apps/web/src/pages/LoginPage.tsx`
- **MembersPage** — `apps/web/src/pages/MembersPage.tsx`
- **NotFoundPage** — `apps/web/src/pages/NotFoundPage.tsx`
- **ReceivedInvitationsPage** — `apps/web/src/pages/ReceivedInvitationsPage.tsx`
- **RegisterPage** — `apps/web/src/pages/RegisterPage.tsx`
- **ResetPasswordPage** — `apps/web/src/pages/ResetPasswordPage.tsx`
- **VerifyEmailPage** — `apps/web/src/pages/VerifyEmailPage.tsx`
- **WebhookCreatePage** — `apps/web/src/pages/WebhookCreatePage.tsx`
- **WebhooksPage** — `apps/web/src/pages/WebhooksPage.tsx`
- **WorkspaceCreatePage** — `apps/web/src/pages/WorkspaceCreatePage.tsx`
- **AdminLayout** — `apps/web/src/pages/admin/sections/AdminLayout.tsx`
- **AuditSection** — `apps/web/src/pages/admin/sections/AuditSection.tsx`
- **UsersSection** — `apps/web/src/pages/admin/sections/UsersSection.tsx`
- **WorkspacesSection** — `apps/web/src/pages/admin/sections/WorkspacesSection.tsx`
- **GenericSettingsLayout** — props: registry, basePath, title, subtitle, can, guard — `apps/web/src/pages/settings/components/GenericSettingsLayout.tsx`
- **SettingsNav** — props: sections, basePath — `apps/web/src/pages/settings/components/SettingsNav.tsx`
- **ProfileSettingsLayout** — `apps/web/src/pages/settings/profile/ProfileSettingsLayout.tsx`
- **GeneralSection** — `apps/web/src/pages/settings/profile/sections/GeneralSection.tsx`
- **NotificationsSection** — `apps/web/src/pages/settings/profile/sections/NotificationsSection.tsx`
- **SecuritySection** — `apps/web/src/pages/settings/profile/sections/SecuritySection.tsx`
- **WorkspaceSettingsLayout** — `apps/web/src/pages/settings/workspace/WorkspaceSettingsLayout.tsx`
- **AuditLogSection** — `apps/web/src/pages/settings/workspace/sections/AuditLogSection.tsx`
- **GeneralSection** — `apps/web/src/pages/settings/workspace/sections/GeneralSection.tsx`
- **JobsSection** — `apps/web/src/pages/settings/workspace/sections/JobsSection.tsx`
- **RolesSection** — `apps/web/src/pages/settings/workspace/sections/RolesSection.tsx`
- **UsersSection** — `apps/web/src/pages/settings/workspace/sections/UsersSection.tsx`

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
- `apps/api/alembic/versions/0005_conversations.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0006_user_profiles.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0007_stored_secrets_expires_at.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0008_webhooks.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0009_notification_preferences.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0010_auth_tokens.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0011_workspace_flags.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0012_api_key_usage.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0013_converge_historical_drift.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0014_session_metadata.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0015_2fa_sessions.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0016_oauth_accounts.py` — function upgrade: () -> None, function downgrade: () -> None
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
  - function record_key_use: (api_key, db, response) -> None
  - function authenticate_websocket_token: (db, token) -> User | None
  - class AuthPrincipal
- `apps/api/src/container.py` — class Container
- `apps/api/src/core/cache.py` — class TtlCache
- `apps/api/src/core/dates.py` — function ensure_utc: (value) -> datetime, function now_utc: () -> datetime
- `apps/api/src/core/metrics.py`
  - function inc: (name, value, **labels) -> None
  - function observe_request: (*, method, path, status) -> None
  - function observe_job_run: (*, key, status) -> None
  - function observe_webhook_delivery: (*, outcome) -> None
  - function render_prometheus: () -> str
  - function reset: () -> None
- `apps/api/src/core/permissions.py` — function register_permission: (permission, *, resource, action) -> str, function permissions_for_role: (role_name) -> list[str]
- `apps/api/src/core/request_id.py` — function get_request_id: () -> str, class RequestIdMiddleware
- `apps/api/src/core/security/crypto.py` — class SecretCipher
- `apps/api/src/core/security/password.py` — class PasswordHasher
- `apps/api/src/core/security/ratelimit.py` — function get_auth_limiter: () -> SlidingWindowLimiter, class SlidingWindowLimiter
- `apps/api/src/core/security/tokens.py`
  - function create_access_token: (user_id, *, session_id, expires_minutes) -> str
  - function decode_access_token: (token) -> dict[str, Any]
  - class OpaqueToken
- `apps/api/src/core/security/totp.py`
  - function generate_secret: (num_bytes) -> bytes
  - function secret_to_base32: (secret) -> str
  - function secret_from_base32: (encoded) -> bytes
  - function otpauth_uri: (*, secret_b32, email, issuer) -> str
  - function current_code: (secret, *, at) -> str
  - function verify: (secret, code, *, at, last_counter) -> int | None
  - _...2 more_
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
- `apps/api/src/email/base.py`
  - class EmailDriver
  - class EmailSendError
  - class EmailMessage
  - class EmailSender
- `apps/api/src/email/console.py` — class ConsoleEmailSender
- `apps/api/src/email/factory.py` — function build_email_sender: () -> EmailSender, function send_email: (message) -> bool
- `apps/api/src/email/smtp.py` — class SmtpConfig, class SmtpEmailSender
- `apps/api/src/email/templates.py`
  - function invitation: (to, *, workspace_name, invite_url, invited_by) -> EmailMessage
  - function notification_email: (to, *, title, body, workspace_name, unsubscribe_url) -> EmailMessage
  - function digest_email: (to, *, items, unsubscribe_url) -> EmailMessage
  - function email_verification: (to, *, verify_url) -> EmailMessage
  - function password_reset: (to, *, reset_url) -> EmailMessage
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
- `apps/api/src/events/webhook_events.py`
  - function register_webhook_event: (event_name, subject) -> str
  - function webhook_event_names: () -> list[str]
  - function webhook_subject_for: (event_name) -> str | None
  - function webhook_event_for_subject: (subject) -> str | None
  - function webhook_subjects: () -> list[str]
- `apps/api/src/jobs/builtin.py`
  - function system_heartbeat: (ctx) -> None
  - function expire_stale_invitations: (ctx) -> None
  - function notifications_daily_digest: (ctx) -> None
  - function retention_cleanup: (ctx) -> None
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
- `apps/api/src/main.py`
  - function lifespan: (app)
  - function root: () -> dict
  - class ApiVersionMiddleware
- `apps/api/src/models/api_key.py` — class ApiKey
- `apps/api/src/models/audit.py` — class AuditLogEntry
- `apps/api/src/models/conversation.py`
  - class Conversation
  - class ConversationParticipant
  - class Message
- `apps/api/src/models/core.py`
  - class Invitation
  - class NotificationPreference
  - class Notification
- `apps/api/src/models/jobs.py`
  - class JobScope
  - class JobRunStatus
  - class JobTrigger
  - class MissedJobPolicy
  - class JobDefinition
  - class JobRun
  - _...1 more_
- `apps/api/src/models/oauth.py` — class OAuthAccount
- `apps/api/src/models/secret.py` — class StoredSecret
- `apps/api/src/models/two_factor.py` — class UserTotpCredential
- `apps/api/src/models/user_profile.py` — class UserProfile
- `apps/api/src/models/webhook.py`
  - class WebhookSubscription
  - class WebhookDeliveryStatus
  - class WebhookDelivery
- `apps/api/src/models/workspace.py`
  - class User
  - class AuthToken
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
  - class ForgotPasswordRequest
  - class ResetPasswordRequest
  - _...32 more_
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
- `apps/api/src/services/conversations.py`
  - class ConversationError
  - class ConversationForbidden
  - class ConversationNotFound
  - class ConversationService
- `apps/api/src/services/jobs.py`
  - function job_to_dict: (d) -> dict
  - function job_run_to_dict: (r, *, schema) -> dict
  - function job_log_to_dict: (e) -> dict
  - class JobError
  - class JobService
- `apps/api/src/services/notifications.py`
  - function unsubscribe_url_for: (token, type, frontend_url) -> str
  - class NotificationSpec
  - class NotificationService
- `apps/api/src/services/oauth.py`
  - function get_provider: (provider_id) -> ProviderConfig
  - function build_authorize_url: (provider, doc, Any], cache, redirect_uri) -> str
  - function consume_state: (cache, state) -> dict[str, Any]
  - function claims_from_id_token: (provider, doc, Any], id_token, cache) -> Any] | None
  - function normalize_identity: (*, provider_id, claims, Any] | None, userinfo, Any]) -> dict[str, Any]
  - function exchange_code: (provider, doc, Any], *, code, redirect_uri) -> dict[str, Any]
  - _...3 more_
- `apps/api/src/services/profile_helpers.py`
  - function escape_like: (q) -> str
  - function format_display_name: (first_name, last_name, fallback) -> str
  - function validate_custom_data: (data) -> None
  - function merge_custom_data: (existing, patch, is_put) -> dict
- `apps/api/src/services/profiles.py` — class ProfileService
- `apps/api/src/services/search_export.py` — class SearchExportService
- `apps/api/src/services/serializers.py`
  - function notification_to_dict: (n, *, workspace_name) -> dict
  - function user_to_dict: (u) -> dict
  - function workspace_to_dict: (w, *, role, permissions) -> dict
  - function profile_to_dict: (p) -> dict
  - function public_projection: (p, user) -> dict
- `apps/api/src/services/two_factor.py` — class TwoFactorError, class TwoFactorService
- `apps/api/src/services/webhook_dispatcher.py` — class WebhookDispatcher
- `apps/api/src/services/webhooks.py`
  - function secret_key_for: (subscription_id) -> str
  - function generate_secret: () -> str
  - function sign_payload: (secret, timestamp, raw_body) -> str
  - function verify_signature: (secret, timestamp, raw_body, signature) -> bool
  - function next_retry_delay: (attempt) -> int | None
  - function validate_url: (url, *, allow_private) -> str
  - _...9 more_
- `apps/api/src/services/workspaces.py`
  - class WorkspaceError
  - class WorkspaceForbidden
  - class WorkspaceConflict
  - class WorkspaceService
- `apps/api/src/settings.py` — class Settings
- `apps/api/src/workflows/__init__.py` — function build_workflows: (registry, bus, connection_manager, cipher) -> None
- `apps/web/src/hooks/useNotificationPreferences.ts`
  - function humanizeType: (type) => string
  - function useNotificationPreferences: (extraTypes, enabled) => void
  - const KNOWN_NOTIFICATION_TYPES
  - const CHANNEL_OPTIONS: Array<{ value: NotificationChannel; label: string }>
  - const NOTIFICATION_TYPE_META: Record<string, { title: string; description: string }>
- `apps/web/src/hooks/useProfile.ts`
  - function useProfile: () => void
  - function useUpdateProfile: () => void
  - function useExportProfile: () => void
  - function useDeleteAccount: () => void
  - function usePublicProfile: (userId) => void
- `apps/web/src/hooks/useWorkspaceQuery.ts` — function useWorkspaceList: (props, TError, TData>) => void, function useWorkspaceCustom: (props, TError, TQuery, TPayload, TData>) => void
- `apps/web/src/lib/avatar.ts`
  - function getInitials: (name) => string
  - function getInitialsFromNames: (firstName?, lastName?, fallbackName?) => string
  - function getAvatarSrc: (avatarUrl?) => string | undefined
  - function getAvatarData: (entity, fallbackEmailAsName) => void
  - const UserProfileAvatar
- `apps/web/src/lib/utils.ts` — function cn: (...inputs) => void, function oktaAdminConsoleFix: (value?) => string | null
- `apps/web/src/providers/authProvider.ts` — function seedWorkspace: (identity) => Promise<void>, const authProvider: AuthProvider
- `apps/web/src/providers/dataProvider.ts`
  - function cancelPendingRefresh: () => void
  - const API_URL
  - const httpClient
  - const dataProvider: DataProvider
- `apps/web/src/providers/liveCache.ts`
  - function upsertThreadMessage: (conversationId, message) => void
  - function removeThreadMessage: (conversationId, messageId) => void
  - function applyMessageCreated: (frame) => void
  - function applyNotificationCreated: (frame) => void
  - function applyConversationRead: (conversationId) => void
- `apps/web/src/providers/liveProvider.ts`
  - function subscribeLive: (channel, handler) => () => void
  - type LiveEventHandler
  - const liveChannels
  - const liveProvider: LiveProvider
- `apps/web/src/providers/queryClient.ts`
  - function clearWorkspaceCaches: (client) => void
  - function clearAllCaches: (client) => void
  - const queryClient
- `apps/web/src/types.ts`
  - function getProfileField: (profile, key, fallback) => unknown
  - function formatDisplayName: (firstName?, lastName?, fallback?) => string
  - function getDisplayNameFromProfile: (profile?, fallback?) => string
  - function getDisplayName: (identity?) => string
  - function getMemberDisplayName: (member) => string
  - function getParticipantDisplayName: (participant) => string
  - _...26 more_
- `apps/web/src/utils/permissions.ts` — function activeWorkspacePermissions: (identity?) => string[]
- `apps/web/src/utils/storage.ts`
  - function getActiveWorkspaceId: () => string | null
  - function setActiveWorkspaceId: (id) => void
  - const tokenStore
  - const identityStore
  - const workspaceStore
- `scripts/dev.py`
  - function main: () -> int
  - function kill_all: (procs, sig) -> None
  - function wait_all: (procs, timeout) -> None

---

# Config

## Environment Variables

- `ACCESS_TOKEN_EXPIRE_MINUTES` (has default) — apps/api/.env.example
- `APP_NAME` (has default) — apps/api/.env.example
- `AUDIT_LOG_RETENTION_DAYS` (has default) — apps/api/.env.example
- `AUTH_RATE_LIMIT_MAX_ATTEMPTS` (has default) — apps/api/.env.example
- `AUTH_RATE_LIMIT_WINDOW_SECONDS` (has default) — apps/api/.env.example
- `CORS_ORIGINS` (has default) — apps/api/.env.example
- `DATABASE_URL` **required** — apps/api/tests/conftest.py
- `DEBUG` (has default) — apps/api/.env.example
- `DOCKER_HOST` (has default) — apps/api/tests/test_nats_integration.py
- `EMAIL_DRIVER` (has default) — apps/api/.env.example
- `EMAIL_FROM` **required** — apps/api/.env.example
- `EMBEDDED_DB_DIR` **required** — apps/api/src/db/embedded.py
- `ENVIRONMENT` (has default) — apps/api/.env.example
- `EVENT_BUS_DRIVER` (has default) — apps/api/.env.example
- `FERNET_KEYS` (has default) — apps/api/.env.example
- `FRONTEND_URL` (has default) — apps/api/.env.example
- `JOBS_DEFAULT_TIMEOUT_SECONDS` (has default) — apps/api/.env.example
- `JOBS_LOG_RETENTION_DAYS` (has default) — apps/api/.env.example
- `JOBS_RUN_RETENTION` (has default) — apps/api/.env.example
- `JOBS_SCHEDULER_TICK_SECONDS` (has default) — apps/api/.env.example
- `NATS_URL` (has default) — apps/api/.env.example
- `NOTIFICATIONS_RETENTION_DAYS` (has default) — apps/api/.env.example
- `REFRESH_TOKEN_EXPIRE_DAYS` (has default) — apps/api/.env.example
- `SECRET_ENCRYPT_VERSION` (has default) — apps/api/.env.example
- `SECRET_KEY` (has default) — apps/api/.env.example
- `SECRET_STORE_DRIVER` (has default) — apps/api/.env.example
- `SMTP_HOST` (has default) — apps/api/.env.example
- `SMTP_PASSWORD` **required** — apps/api/.env.example
- `SMTP_PORT` (has default) — apps/api/.env.example
- `SMTP_TIMEOUT_S` (has default) — apps/api/.env.example
- `SMTP_USE_TLS` (has default) — apps/api/.env.example
- `SMTP_USERNAME` **required** — apps/api/.env.example
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
- ratelimit — `apps/api/src/core/security/ratelimit.py`
- auth — `apps/api/src/services/auth.py`
- authProvider — `apps/web/src/providers/authProvider.ts`

---

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

---

# Test Coverage

> **21%** of routes and models are covered by tests
> 35 test files found

## Covered Routes

- GET:
- POST:
- GET:/

## Covered Models

- ApiKey
- AuditLogEntry
- Conversation
- ConversationParticipant
- Message
- Invitation
- NotificationPreference
- Notification
- JobDefinition
- JobRun
- JobLogEntry
- StoredSecret
- UserProfile
- WebhookSubscription
- WebhookDelivery
- User
- AuthToken
- RefreshToken
- Workspace
- Role
- WorkspaceMember

---

# CI/CD Pipelines

## GitHub Actions (1 workflow)

| Workflow | Triggers | Jobs | Deploy | Environments |
|---|---|---|---|---|
| ci | pull_request, push | 4 | — | — |

### ci

> `.github/workflows/ci.yml`

- **api-lint** on `ubuntu-latest` — 4 steps
  - `actions/checkout@v4`
  - `astral-sh/setup-uv@v5`
- **api-test** on `ubuntu-latest` — 4 steps
  - `actions/checkout@v4`
  - `astral-sh/setup-uv@v5`
- **db-check** on `ubuntu-latest` — 4 steps
  - `actions/checkout@v4`
  - `astral-sh/setup-uv@v5`
- **web-build** on `ubuntu-latest` — 4 steps
  - `actions/checkout@v4`
  - `actions/setup-node@v4`

---
_Source: .github/workflows/ci.yml_
_Generated by codesight-cicd-plugin_

---

_Generated by [codesight](https://github.com/Houseofmvps/codesight) — see your codebase clearly_