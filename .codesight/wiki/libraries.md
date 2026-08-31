# Libraries

> **Navigation aid.** Library inventory extracted via AST. Read the source files listed here before modifying exported functions.

**123 library files** across 5 modules

## Api (73 files)

- `apps/api/src/schemas/api.py` — LoginRequest, RegisterRequest, TokenResponse, RefreshRequest, WorkspaceCreate, WorkspaceUpdate, …
- `apps/api/src/jobs/registry.py` — validate_cron_schedule, next_cron_occurrence, validate_params, default_params, register_builtin_jobs, ValidationError, …
- `apps/api/src/jobs/capture.py` — run_log_collector, set_run_log_collector, reset_run_log_collector, install_run_capture, uninstall_run_capture, CapturedEntry, …
- `apps/api/src/models/jobs.py` — JobScope, JobRunStatus, JobTrigger, MissedJobPolicy, JobDefinition, JobRun, …
- `apps/api/src/api/crud.py` — parse_query, apply_query, run_list, QuerySpec, InvalidQuery
- `apps/api/src/api/deps.py` — get_container, require_key_permission, require_permission, authenticate_websocket_token, AuthPrincipal
- `apps/api/src/events/bus.py` — EventMetadata, EventEnvelope, EventBus, PublishError, SubscriptionError
- `apps/api/src/models/workspace.py` — User, RefreshToken, Workspace, Role, WorkspaceMember
- `apps/api/src/services/agents.py` — AgentError, AgentNotFound, AgentConflict, AgentValidation, AgentService
- `apps/api/src/services/jobs.py` — job_to_dict, job_run_to_dict, job_log_to_dict, JobError, JobService
- `apps/api/src/services/serializers.py` — notification_to_dict, user_to_dict, workspace_to_dict, profile_to_dict, public_projection
- `apps/api/src/agents/handlers/base.py` — AgentRequest, AgentContext, AgentEvent, AgentHandler
- `apps/api/src/agents/runners/base.py` — RunSpec, RunHandle, AgentEvent, RunnerService
- `apps/api/src/db/base.py` — StringUUID, Base, TimestampMixin, StrEnum
- `apps/api/src/services/api_keys.py` — ApiKeyError, ApiKeyForbidden, ApiKeyNotFound, ApiKeyService
- `apps/api/src/services/conversations.py` — ConversationError, ConversationForbidden, ConversationNotFound, ConversationService
- `apps/api/src/services/workspace_settings.py` — WorkspaceSettingsError, WorkspaceSettingsNotFound, WorkspaceSettingsValidation, WorkspaceSettingsService
- `apps/api/src/services/workspaces.py` — WorkspaceError, WorkspaceForbidden, WorkspaceConflict, WorkspaceService
- `apps/api/alembic/env.py` — run_migrations_offline, do_run_migrations, run_migrations_online
- `apps/api/src/core/security/tokens.py` — create_access_token, decode_access_token, OpaqueToken
- `apps/api/src/db/embedded.py` — data_dir, ensure_started, embedded_uri
- `apps/api/src/events/publisher.py` — audit_payload, publish_event, publish_audit
- `apps/api/src/jobs/builtin.py` — system_heartbeat, expire_stale_invitations, demo_global_daily_report
- `apps/api/src/models/conversation.py` — Conversation, ConversationParticipant, Message
- `apps/api/src/services/auth.py` — AuthError, TokenPair, AuthService
- _…and 48 more files_

## Agent (36 files)

- `agent/skills/architecture-viz-studio/assets/scene/primitives.js` — box, tower, house, warehouse, makeCanvasTexture, corrugate, …
- `agent/skills/github-sync/scripts/parse-artifacts.py` — extract_story_id, parse_frontmatter, read_file, shorten_title, detect_synced, extract_status, …
- `agent/skills/ai-multimodal/scripts/check_setup.py` — print_header, print_success, print_warning, print_error, print_info, check_dependencies, …
- `agent/skills/ai-multimodal/scripts/gemini_batch_process.py` — find_api_key, get_default_model, validate_model_task_combination, infer_task_from_file, get_mime_type, upload_file, …
- `agent/skills/architecture-viz-studio/assets/scroll/scroll-journey.js` — camParam, cometParam, updateCamera, tickFeeders, tickRoute, journeyCurve, …
- `agent/skills/slide-maker/deck-template/scripts/lib/deck-driver.mjs` — enterPresentMode, makeDeckRequire, buildStandalone, serveDir, launchBrowser, openDeck, …
- `agent/skills/architecture-viz-studio/assets/scene/scene-setup.js` — resize, mat, glowMat, PALETTE, REDUCED, state, …
- `agent/skills/bmad-auto/scripts/context-usage.py` — claude_projects_dir, iter_transcripts, find_transcript_by_session_id, find_transcript_by_agent, parse_context_window, parse_transcript, …
- `agent/skills/jira-to-local/scripts/config.mjs` — findConfigPath, findWorkspaceRoot, validateConfigFile, loadConfig, issueTypeConfig, instructionsFor, …
- `agent/skills/ai-multimodal/scripts/media_optimizer.py` — load_env_files, check_ffmpeg, get_media_info, optimize_video, optimize_audio, optimize_image, …
- `agent/skills/mcp-builder/scripts/evaluation.py` — parse_evaluation_file, extract_xml_content, parse_headers, parse_env_vars, agent_loop, evaluate_single_task, …
- `agent/skills/ai-multimodal/scripts/document_converter.py` — find_api_key, find_project_root, get_mime_type, upload_file, convert_to_markdown, batch_convert, …
- `agent/skills/book-converter/scripts/merge_book.py` — extract_headers, fix_image_paths, load_chapter_map, process_book, generate_toc, detect_book_title, …
- `agent/skills/jira-to-local/scripts/jira-api.mjs` — credentials, connect, apiGet, apiGetSoft, graphqlSoft, getAllPages, …
- `agent/skills/book-converter/scripts/convert_book.py` — sanitize_name, setup_project_structure, extract_epub_with_pandoc, copy_formatting_standards, create_progress_file, main
- `agent/skills/jira-to-local/scripts/adf.mjs` — adfToMarkdown, adfToPlainText, renderValue, parseDevelopment, formatSeconds, cell
- `agent/skills/architecture-viz-studio/assets/diagrams/erd-diagram.js` — buildErd, drawErdLines, initErd, ERD, ERD_RELS
- `agent/skills/architecture-viz-studio/assets/scene/render-loop.js` — setComposer, frame, startRender, stopRender, requestRender
- `agent/skills/architecture-viz-studio/sample/diagrams/erd-diagram.js` — buildErd, drawErdLines, initErd, ERD, ERD_RELS
- `agent/skills/mcp-builder/scripts/connections.py` — create_connection, MCPConnection, MCPConnectionStdio, MCPConnectionSSE, MCPConnectionHTTP
- `agent/skills/skill-from-book/scripts/init-book-skill.py` — create_skill_md, create_progress_md, create_guidelines_md, init_skill, main
- `agent/skills/architecture-viz-studio/assets/diagrams/component-detail-modal.js` — initDrill, DETAIL, ENGINE_DESIGN, LANES_DESIGN
- `agent/skills/architecture-viz-studio/sample/diagrams/component-detail-modal.js` — initDrill, DETAIL, ENGINE_DESIGN, LANES_DESIGN
- `agent/skills/atlassian-rest/scripts/confluence-format.mjs` — markdownToStorage, storageToMarkdown, htmlInlineToMarkdown, stripHtmlTags
- `agent/skills/book-converter/scripts/analyze_structure.py` — extract_headers, detect_issues, generate_structure_report, main
- _…and 11 more files_

## Web (8 files)

- `apps/web/src/types.ts` — getProfileField, formatDisplayName, getDisplayNameFromProfile, getDisplayName, getMemberDisplayName, getParticipantDisplayName, …
- `apps/web/src/lib/avatar.ts` — getInitials, getInitialsFromNames, getAvatarSrc, getAvatarData, parseAvatarValue, ParsedAvatar, …
- `apps/web/src/providers/liveCache.ts` — upsertThreadMessage, removeThreadMessage, applyMessageCreated, applyNotificationCreated, applyConversationRead
- `apps/web/src/hooks/useProfile.ts` — useProfile, useUpdateProfile, useExportProfile, useDeleteAccount
- `apps/web/src/providers/liveProvider.ts` — subscribeLive, LiveEventHandler, liveChannels, liveProvider
- `apps/web/src/providers/queryClient.ts` — clearWorkspaceCaches, clearAllCaches, queryClient
- `apps/web/src/lib/utils.ts` — cn, oktaAdminConsoleFix
- `apps/web/src/utils/permissions.ts` — activeWorkspacePermissions

## _bmad (5 files)

- `_bmad/scripts/memlog.py` — now, resolve, split, render, touch, write_atomic, …
- `_bmad/scripts/config_utils.py` — load_toml, structural_merge, merge_layers, load_central_config, load_customization, ConfigError
- `_bmad/scripts/resolve_customization.py` — find_project_root, extract_key, write_json_stdout, main
- `_bmad/scripts/render_skill.py` — render, main, RenderError
- `_bmad/scripts/resolve_config.py` — extract_key, main

## Scripts (1 files)

- `scripts/dev.py` — main, kill_all, wait_all

---
_Back to [overview.md](./overview.md)_