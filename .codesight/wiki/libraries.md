# Libraries

> **Navigation aid.** Library inventory extracted via AST. Read the source files listed here before modifying exported functions.

**118 library files** across 3 modules

## Api (90 files)

- `apps/api/src/schemas/api.py` — LoginRequest, RegisterRequest, TokenResponse, RefreshRequest, ForgotPasswordRequest, ResetPasswordRequest, …
- `apps/api/src/services/webhooks.py` — secret_key_for, generate_secret, sign_payload, verify_signature, next_retry_delay, validate_url, …
- `apps/api/src/jobs/registry.py` — validate_cron_schedule, next_cron_occurrence, validate_params, default_params, register_builtin_jobs, ValidationError, …
- `apps/api/src/api/deps.py` — get_container, uuid_or_404, require_deployment_admin, require_key_permission, require_permission, resolve_or_deny, …
- `apps/api/src/jobs/capture.py` — run_log_collector, set_run_log_collector, reset_run_log_collector, install_run_capture, uninstall_run_capture, CapturedEntry, …
- `apps/api/src/services/oauth.py` — get_provider, build_authorize_url, consume_state, normalize_identity, exchange_code, claims_from_id_token, …
- `apps/api/src/core/security/totp.py` — generate_secret, secret_to_base32, secret_from_base32, otpauth_uri, current_code, verify, …
- `apps/api/src/services/serializers.py` — notification_to_dict, user_to_dict, workspace_to_dict, profile_to_dict, session_to_dict, strip_private_custom_data, …
- `apps/api/src/models/jobs.py` — JobScope, JobRunStatus, JobTrigger, MissedJobPolicy, JobDefinition, JobRun, …
- `apps/api/src/models/workspace.py` — User, AuthToken, RefreshToken, Workspace, Role, MemberStatus, …
- `apps/api/src/services/workspaces.py` — is_owner_role_name, is_manager_role_name, WorkspaceError, WorkspaceForbidden, WorkspaceConflict, WorkspaceNotFound, …
- `apps/api/src/core/metrics.py` — inc, observe_request, observe_job_run, observe_webhook_delivery, render_prometheus, reset
- `apps/api/src/core/security/cookies.py` — cookie_secure_for, set_refresh_cookie, clear_refresh_cookie, get_refresh_token, browser_flow, require_csrf
- `apps/api/src/events/bus.py` — subject_matches, EventMetadata, EventEnvelope, EventBus, PublishError, SubscriptionError
- `apps/api/src/jobs/builtin.py` — system_heartbeat, expire_stale_invitations, notifications_daily_digest, retention_cleanup, api_key_cleanup, demo_global_daily_report
- `apps/api/src/email/templates.py` — invitation, notification_email, digest_email, email_verification, password_reset
- `apps/api/src/events/webhook_events.py` — register_webhook_event, webhook_event_names, webhook_subject_for, webhook_event_for_subject, webhook_subjects
- `apps/api/src/seed.py` — main, MembershipRow, InvitationRow, ApiKeyRow, NotificationRow
- `apps/api/src/services/jobs.py` — job_to_dict, job_run_to_dict, job_log_to_dict, JobError, JobService
- `apps/api/src/api/crud.py` — parse_query, apply_query, QuerySpec, InvalidQuery
- `apps/api/src/db/base.py` — StringUUID, Base, TimestampMixin, StrEnum
- `apps/api/src/email/base.py` — EmailDriver, EmailSendError, EmailMessage, EmailSender
- `apps/api/src/services/api_keys.py` — ApiKeyError, ApiKeyForbidden, ApiKeyNotFound, ApiKeyService
- `apps/api/src/services/auth.py` — AuthError, CurrentSessionError, TokenPair, AuthService
- `apps/api/src/services/conversations.py` — ConversationError, ConversationForbidden, ConversationNotFound, ConversationService
- _…and 65 more files_

## Web (27 files)

- `apps/web/src/types.ts` — getProfileField, formatDisplayName, getDisplayNameFromProfile, getDisplayName, getDisplayNameFromRow, memberOptionLabel, …
- `apps/web/src/utils/storage.ts` — getActiveWorkspaceId, setActiveWorkspaceId, resetSessionState, sessionHint, tokenStore, identityStore, …
- `apps/web/src/lib/mentions.ts` — rankMentionTargets, pickerIndex, nextPickerIndex, mentionUrlTransform, mentionRemarkPlugin, MentionTarget, …
- `apps/web/src/providers/queryClient.ts` — isClientError, isServerError, isNoResponseError, shouldRetry, clearWorkspaceCaches, clearAllCaches, …
- `apps/web/src/hooks/useProfile.ts` — useTargetUserId, useProfile, useUpdateProfile, useExportProfile, useDeleteAccount, usePublicProfile
- `apps/web/src/providers/liveCache.ts` — upsertThreadMessage, removeThreadMessage, applyMessageCreated, applyNotificationCreated, invalidateUnreadCounts, applyConversationRead
- `apps/web/src/hooks/useNotificationPreferences.ts` — humanizeType, useNotificationPreferences, KNOWN_NOTIFICATION_TYPES, CHANNEL_OPTIONS, NOTIFICATION_TYPE_META
- `apps/web/src/lib/avatar.ts` — getInitials, getInitialsFromNames, getAvatarSrc, getAvatarData, UserProfileAvatar
- `apps/web/src/providers/dataProvider.ts` — cancelPendingRefresh, ensureSession, API_URL, httpClient, dataProvider
- `apps/web/e2e/mock-api.ts` — mockApi, mockApiTwoFactor, IDENTITY, ACCESS_TOKEN
- `apps/web/src/hooks/query-keys-guard.ts` — stripComments, useUpdateProfileWindow, countAuthInvalidations, useX
- `apps/web/src/providers/liveProvider.ts` — subscribeLive, LiveEventHandler, liveChannels, liveProvider
- `apps/web/src/providers/authProvider.ts` — seedWorkspace, afterAuthRedirect, authProvider
- `apps/web/src/hooks/useWorkspaceQuery.ts` — useWorkspaceList, useWorkspaceCustom
- `apps/web/src/lib/link-url.ts` — normalizeLinkUrl, isAllowedLinkHref
- `apps/web/src/lib/utils.ts` — cn, oktaAdminConsoleFix
- `apps/web/src/providers/adminListQuery.ts` — adminListQuery, AdminListQueryInput
- `apps/web/src/providers/refreshLock.ts` — hasRefreshLock, withRefreshLock
- `apps/web/src/providers/resourcePaths.ts` — resourcePath, hasReadById
- `apps/web/e2e/mock-api.typecheck.ts` — checkIdentityContract
- `apps/web/src/hooks/target-user.ts` — resolveTargetUserId
- `apps/web/src/lib/notificationLink.ts` — notificationLinkUrl
- `apps/web/src/lib/role-cap.ts` — roleCapNotice
- `apps/web/src/lib/sameOriginPath.ts` — sameOriginPath
- `apps/web/src/utils/credentialPost.ts` — postCredentials
- _…and 2 more files_

## Scripts (1 files)

- `scripts/dev.py` — api_env_file, dev_allowed_origins, main, kill_all, wait_all

---
_Back to [overview.md](./overview.md)_