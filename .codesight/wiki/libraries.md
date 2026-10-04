# Libraries

> **Navigation aid.** Library inventory extracted via AST. Read the source files listed here before modifying exported functions.

**106 library files** across 3 modules

## Api (89 files)

- `apps/api/src/schemas/api.py` — LoginRequest, RegisterRequest, TokenResponse, RefreshRequest, ForgotPasswordRequest, ResetPasswordRequest, …
- `apps/api/src/services/webhooks.py` — secret_key_for, generate_secret, sign_payload, verify_signature, next_retry_delay, validate_url, …
- `apps/api/src/jobs/registry.py` — validate_cron_schedule, next_cron_occurrence, validate_params, default_params, register_builtin_jobs, ValidationError, …
- `apps/api/src/jobs/capture.py` — run_log_collector, set_run_log_collector, reset_run_log_collector, install_run_capture, uninstall_run_capture, CapturedEntry, …
- `apps/api/src/services/oauth.py` — get_provider, build_authorize_url, consume_state, claims_from_id_token, normalize_identity, exchange_code, …
- `apps/api/src/core/security/totp.py` — generate_secret, secret_to_base32, secret_from_base32, otpauth_uri, current_code, verify, …
- `apps/api/src/models/jobs.py` — JobScope, JobRunStatus, JobTrigger, MissedJobPolicy, JobDefinition, JobRun, …
- `apps/api/src/api/deps.py` — get_container, require_key_permission, require_permission, record_key_use, authenticate_websocket_token, AuthPrincipal
- `apps/api/src/core/metrics.py` — inc, observe_request, observe_job_run, observe_webhook_delivery, render_prometheus, reset
- `apps/api/src/core/security/cookies.py` — cookie_secure_for, set_refresh_cookie, clear_refresh_cookie, get_refresh_token, browser_flow, require_csrf
- `apps/api/src/jobs/builtin.py` — system_heartbeat, expire_stale_invitations, notifications_daily_digest, retention_cleanup, api_key_cleanup, demo_global_daily_report
- `apps/api/src/models/workspace.py` — User, AuthToken, RefreshToken, Workspace, Role, WorkspaceMember
- `apps/api/src/api/crud.py` — parse_query, apply_query, QuerySpec, InvalidQuery
- `apps/api/src/email/templates.py` — invitation, notification_email, digest_email, email_verification, password_reset
- `apps/api/src/events/bus.py` — EventMetadata, EventEnvelope, EventBus, PublishError, SubscriptionError
- `apps/api/src/events/webhook_events.py` — register_webhook_event, webhook_event_names, webhook_subject_for, webhook_event_for_subject, webhook_subjects
- `apps/api/src/services/jobs.py` — job_to_dict, job_run_to_dict, job_log_to_dict, JobError, JobService
- `apps/api/src/services/serializers.py` — notification_to_dict, user_to_dict, workspace_to_dict, profile_to_dict, public_projection
- `apps/api/src/services/workspaces.py` — WorkspaceError, WorkspaceForbidden, WorkspaceConflict, WorkspaceNotFound, WorkspaceService
- `apps/api/src/db/base.py` — StringUUID, Base, TimestampMixin, StrEnum
- `apps/api/src/email/base.py` — EmailDriver, EmailSendError, EmailMessage, EmailSender
- `apps/api/src/services/api_keys.py` — ApiKeyError, ApiKeyForbidden, ApiKeyNotFound, ApiKeyService
- `apps/api/src/services/conversations.py` — ConversationError, ConversationForbidden, ConversationNotFound, ConversationService
- `apps/api/src/services/profile_helpers.py` — escape_like, format_display_name, validate_custom_data, merge_custom_data
- `apps/api/alembic/env.py` — run_migrations_offline, do_run_migrations, run_migrations_online
- _…and 64 more files_

## Web (16 files)

- `apps/web/src/types.ts` — getProfileField, formatDisplayName, getDisplayNameFromProfile, getDisplayName, getMemberDisplayName, getParticipantDisplayName, …
- `apps/web/src/utils/storage.ts` — getActiveWorkspaceId, setActiveWorkspaceId, sessionHint, tokenStore, identityStore, workspaceStore, …
- `apps/web/src/lib/mentions.ts` — rankMentionTargets, pickerIndex, mentionUrlTransform, mentionRemarkPlugin, MentionTarget, MENTION_SCHEME, …
- `apps/web/src/providers/liveCache.ts` — upsertThreadMessage, removeThreadMessage, applyMessageCreated, applyNotificationCreated, invalidateUnreadCounts, applyConversationRead
- `apps/web/src/hooks/useNotificationPreferences.ts` — humanizeType, useNotificationPreferences, KNOWN_NOTIFICATION_TYPES, CHANNEL_OPTIONS, NOTIFICATION_TYPE_META
- `apps/web/src/hooks/useProfile.ts` — useProfile, useUpdateProfile, useExportProfile, useDeleteAccount, usePublicProfile
- `apps/web/src/lib/avatar.ts` — getInitials, getInitialsFromNames, getAvatarSrc, getAvatarData, UserProfileAvatar
- `apps/web/src/providers/dataProvider.ts` — cancelPendingRefresh, ensureSession, API_URL, httpClient, dataProvider
- `apps/web/src/providers/liveProvider.ts` — subscribeLive, LiveEventHandler, liveChannels, liveProvider
- `apps/web/e2e/mock-api.ts` — mockApi, IDENTITY, ACCESS_TOKEN
- `apps/web/src/providers/queryClient.ts` — clearWorkspaceCaches, clearAllCaches, queryClient
- `apps/web/src/hooks/useWorkspaceQuery.ts` — useWorkspaceList, useWorkspaceCustom
- `apps/web/src/lib/utils.ts` — cn, oktaAdminConsoleFix
- `apps/web/src/providers/authProvider.ts` — seedWorkspace, authProvider
- `apps/web/src/lib/notificationLink.ts` — notificationLinkUrl
- `apps/web/src/utils/permissions.ts` — activeWorkspacePermissions

## Scripts (1 files)

- `scripts/dev.py` — api_env_file, main, kill_all, wait_all

---
_Back to [overview.md](./overview.md)_