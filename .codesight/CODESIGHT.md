# saas-template — AI Context Map

> **Stack:** fastapi | sqlalchemy | react | typescript
> **Monorepo:** api, saas-template-web

> 62 routes | 19 models | 68 components | 123 lib files | 34 env vars | 5 middleware | 26% test coverage
> **Token savings:** this file is ~12,700 tokens. Without it, AI exploration would cost ~108,600 tokens. **Saves ~95,900 tokens per conversation.**
> **Last scanned:** 2026-08-31 01:43 — re-run after significant changes

---

# Routes

## CRUD Resources

- **``** GET | POST | GET/:id | PUT/:id | DELETE/:id
- **`/{agent_id}/secrets`** GET | GET/:id | PUT/:id | DELETE/:id → Secret
- **`/global`** GET | GET/:id | PATCH/:id → Global

## Other Routes

- `GET` `/effective-permissions` params()
- `POST` `/register` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/login` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/refresh` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/logout` params() → in: RegisterRequest, out: TokenResponse [auth]
- `GET` `/me` params() → out: TokenResponse
- `GET` `/unread-count` params() → in: st
- `PATCH` `/{conversation_id}/read` params(conversation_id)
- `PATCH` `/{conversation_id}/unread` params(conversation_id)
- `PATCH` `/{conversation_id}/archive` params(conversation_id)
- `GET` `/{conversation_id}/messages` params(conversation_id) → in: st
- `GET` `/{conversation_id}/session-history` params(conversation_id) → in: st [auth, db]
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
- `GET` `/readyz` params()
- `GET` `/me/profile` params() → in: Use
- `PUT` `/me/profile` params() → in: ProfileUpdate [db]
- `PATCH` `/me/profile` params() → in: ProfileUpdate [db]
- `GET` `/users/{user_id}/profile` params(user_id) → in: Use
- `GET` `/me/export` params() → in: Use
- `GET` `/users/{user_id}/export` params(user_id) → in: Use
- `DELETE` `/me` params() → in: DeleteMeRequest [db]
- `DELETE` `/users/{user_id}` params(user_id) → in: DeleteMeRequest [db]
- `GET` `/permission-catalog` params()
- `GET` `/` params() ✓

---

# Schema

### Agent
- id: str (pk, default)
- workspace_id: str (index)
- slug: String
- name: String
- description: Text (nullable)
- avatar: String (nullable)
- system_prompt: Text (nullable)
- model: String (nullable)
- temperature: Float (nullable)
- max_tokens: Integer (nullable)
- tool_allowlist: JSON (nullable)
- mcp_servers: JSON (default)
- execution_target: String (nullable)
- role_id: unknown (index, nullable)
- skills: JSON (default)
- is_active: Boolean (default)
- custom_data: JSON (default)
- created_by_user_id: unknown (index, nullable)
- updated_by_user_id: unknown (index, nullable)

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

### Conversation
- id: str (pk, default)
- workspace_id: str (index)
- created_by_user_id: str (index)
- title: String (nullable)
- entity_type: String (default, index)
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
- agent_session_ref: String (nullable)

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

### WorkspaceSetting
- id: str (pk, default)
- workspace_id: str (index)
- key: String
- value: JSON (default)
- updated_by_user_id: unknown (index, nullable)

---

# Components

- **App** — `agent/skills/slide-maker/deck-template/src/App.jsx`
- **Background** — `agent/skills/slide-maker/deck-template/src/components/Background.jsx`
- **Diagram** — props: src, alt, id, className — `agent/skills/slide-maker/deck-template/src/components/Diagram.jsx`
- **FORMATS** — `agent/skills/slide-maker/deck-template/src/components/ExportMenu.jsx`
- **GridView** — props: slides, navItems, current, onPick — `agent/skills/slide-maker/deck-template/src/components/GridView.jsx`
- **NotesPanel** — props: notes, label — `agent/skills/slide-maker/deck-template/src/components/NotesPanel.jsx`
- **PresentBar** — props: current, total, onPrev, onNext, tool, onSetTool, onClearInk, onExit, visible — `agent/skills/slide-maker/deck-template/src/components/PresentBar.jsx`
- **PresentMode** — props: tool, clearSignal — `agent/skills/slide-maker/deck-template/src/components/PresentMode.jsx`
- **SlideRail** — props: slides, navItems, current, onGoTo, editOn, onToggleEdit — `agent/skills/slide-maker/deck-template/src/components/SlideRail.jsx`
- **CANVAS_W** — `agent/skills/slide-maker/deck-template/src/components/SlideThumb.jsx`
- **StaggerContainer** — props: className — `agent/skills/slide-maker/deck-template/src/components/SlideTransition.jsx`
- **TopBar** — props: deckName, current, total, gridOpen, onToggleGrid, notesOpen, onToggleNotes, zoom, onZoom, onFit — `agent/skills/slide-maker/deck-template/src/components/TopBar.jsx`
- **TransitionMenu** — props: value, onChange — `agent/skills/slide-maker/deck-template/src/components/TransitionMenu.jsx`
- **HeroMetrics** — `agent/skills/slide-maker/deck-template/src/slides/00-EXAMPLE-hero-metrics.jsx`
- **App** — `agent/skills/slides-generator/assets/template/src/App.jsx`
- **Background** — props: variant, animate, className — `agent/skills/slides-generator/assets/template/src/components/Background.jsx`
- **ExportModal** — props: isOpen, onClose, totalSlides, currentSlide, goToSlide, presentationName — `agent/skills/slides-generator/assets/template/src/components/ExportModal.jsx`
- **Navigation** — props: currentSlide, totalSlides, navItems, onPrev, onNext, onGoTo, onExport — `agent/skills/slides-generator/assets/template/src/components/Navigation.jsx`
- **FadeIn** — props: delay, className — `agent/skills/slides-generator/assets/template/src/components/SlideTransition.jsx`
- **App** — `apps/web/src/App.tsx`
- **AppLayout** — `apps/web/src/components/AppLayout.tsx`
- **NotificationCenter** — `apps/web/src/components/NotificationCenter.tsx`
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
- **AgentCreatePage** — `apps/web/src/pages/agents/AgentCreatePage.tsx`
- **AgentEditPage** — `apps/web/src/pages/agents/AgentEditPage.tsx`
- **AgentsPage** — `apps/web/src/pages/agents/AgentsPage.tsx`
- **ProfileSettingsPage** — `apps/web/src/pages/settings/ProfileSettingsPage.tsx`
- **GenericSettingsLayout** — props: registry, basePath, title, subtitle, can, guard — `apps/web/src/pages/settings/components/GenericSettingsLayout.tsx`
- **SettingsNav** — props: sections, basePath — `apps/web/src/pages/settings/components/SettingsNav.tsx`
- **WorkspaceSettingsLayout** — `apps/web/src/pages/settings/workspace/WorkspaceSettingsLayout.tsx`
- **AgentsGeneralSection** — `apps/web/src/pages/settings/workspace/sections/AgentsGeneralSection.tsx`
- **AgentsSandboxSection** — `apps/web/src/pages/settings/workspace/sections/AgentsSandboxSection.tsx`
- **AuditLogSection** — `apps/web/src/pages/settings/workspace/sections/AuditLogSection.tsx`
- **GeneralSection** — `apps/web/src/pages/settings/workspace/sections/GeneralSection.tsx`
- **JobsSection** — `apps/web/src/pages/settings/workspace/sections/JobsSection.tsx`
- **RolesSection** — `apps/web/src/pages/settings/workspace/sections/RolesSection.tsx`
- **UsersSection** — `apps/web/src/pages/settings/workspace/sections/UsersSection.tsx`

---

# Libraries

- `_bmad/scripts/config_utils.py`
  - function load_toml: (path, *, required) -> dict[str, Any]
  - function structural_merge: (base, override) -> Any
  - function merge_layers: (layers, Any]]) -> dict[str, Any]
  - function load_central_config: (project_root) -> dict[str, Any]
  - function load_customization: (project_root, skill_dir) -> dict[str, Any]
  - class ConfigError
- `_bmad/scripts/memlog.py`
  - function now: () -> str
  - function resolve: (args) -> Path
  - function split: (text) -> tuple[dict, str]
  - function render: (meta, body) -> str
  - function touch: (meta) -> None
  - function write_atomic: (path, text) -> None
  - _...7 more_
- `_bmad/scripts/render_skill.py`
  - function render: (project_root, skill_dir) -> Path
  - function main: () -> int
  - class RenderError
- `_bmad/scripts/resolve_config.py` — function extract_key: (data, dotted_key), function main: () -> int
- `_bmad/scripts/resolve_customization.py`
  - function find_project_root: (start) -> Path | None
  - function extract_key: (data, dotted_key)
  - function write_json_stdout: (output) -> None
  - function main: () -> int
- `agent/skills/ai-multimodal/scripts/check_setup.py`
  - function print_header: (text)
  - function print_success: (text)
  - function print_warning: (text)
  - function print_error: (text)
  - function print_info: (text)
  - function check_dependencies: ()
  - _...7 more_
- `agent/skills/ai-multimodal/scripts/document_converter.py`
  - function find_api_key: () -> Optional[str]
  - function find_project_root: () -> Path
  - function get_mime_type: (file_path) -> str
  - function upload_file: (client, file_path, verbose) -> Any
  - function convert_to_markdown: (client, file_path, model, custom_prompt, verbose, max_retries) -> Dict[str, Any]
  - function batch_convert: (files, output_file, auto_name, model, custom_prompt, verbose) -> List[Dict[str, Any]]
  - _...1 more_
- `agent/skills/ai-multimodal/scripts/gemini_batch_process.py`
  - function find_api_key: () -> Optional[str]
  - function get_default_model: (task) -> str
  - function validate_model_task_combination: (model, task) -> None
  - function infer_task_from_file: (file_path) -> str
  - function get_mime_type: (file_path) -> str
  - function upload_file: (client, file_path, verbose) -> Any
  - _...7 more_
- `agent/skills/ai-multimodal/scripts/media_optimizer.py`
  - function load_env_files: ()
  - function check_ffmpeg: () -> bool
  - function get_media_info: (file_path) -> Dict[str, Any]
  - function optimize_video: (input_path, output_path, target_size_mb, max_duration, quality, resolution, verbose) -> bool
  - function optimize_audio: (input_path, output_path, target_size_mb, bitrate, sample_rate, verbose) -> bool
  - function optimize_image: (input_path, output_path, max_width, quality, verbose) -> bool
  - _...2 more_
- `agent/skills/architecture-viz-studio/assets/diagrams/component-detail-modal.js`
  - function initDrill: ({...}, lanes, detail, drill, panZoom, // pass attachPanZoom from pan-zoom-viewport.js
}) => void
  - const DETAIL
  - const ENGINE_DESIGN
  - const LANES_DESIGN
- `agent/skills/architecture-viz-studio/assets/diagrams/edge-hit-proxies.js` — function tagSvgEdges: (root, {...}, prefix, idAttr }) => void
- `agent/skills/architecture-viz-studio/assets/diagrams/erd-diagram.js`
  - function buildErd: (erdBody, data, rels, opts) => void
  - function drawErdLines: (rels) => void
  - function initErd: ({...}, rels, drill, panZoom, intro, // caption above the grid (HTML) => void
  - const ERD
  - const ERD_RELS
- `agent/skills/architecture-viz-studio/assets/diagrams/overlay-lens-system.js` — function initOverlays: ({...}, overlays, reduced) => void, const OVERLAYS
- `agent/skills/architecture-viz-studio/assets/diagrams/pan-zoom-viewport.js` — function attachPanZoom: (opts) => void
- `agent/skills/architecture-viz-studio/assets/scene/post-processing.js` — function makeComposer: ({...}, camera, renderer, opts) => void
- `agent/skills/architecture-viz-studio/assets/scene/primitives.js`
  - function box: (w, h, d, color, x, z, {...}, rounded, ry, shadow, material) => void
  - function tower: (x, z, w, h, d, ry) => void
  - function house: (x, z, w, h, d, ry) => void
  - function warehouse: (x, z, w, h, d, ry) => void
  - function makeCanvasTexture: (w, h, draw) => void
  - function corrugate: (ctx, w, h, base, rib) => void
  - _...15 more_
- `agent/skills/architecture-viz-studio/assets/scene/render-loop.js`
  - function setComposer: (c, resizeFn) => void
  - function frame: (_time, dtMs) => void
  - function startRender: () => void
  - function stopRender: () => void
  - function requestRender
- `agent/skills/architecture-viz-studio/assets/scene/scene-setup.js`
  - function resize: () => void
  - function mat: (color, opts) => void
  - function glowMat: (color, intensity) => void
  - const PALETTE
  - const REDUCED
  - const state
  - _...5 more_
- `agent/skills/architecture-viz-studio/assets/scroll/scroll-journey.js`
  - function camParam: (p) => void
  - function cometParam: (p) => void
  - function updateCamera: (p) => void
  - function tickFeeders: (p, dt) => void
  - function tickRoute: (p) => void
  - const journeyCurve
  - _...7 more_
- `agent/skills/architecture-viz-studio/sample/diagrams/component-detail-modal.js`
  - function initDrill: ({...}, lanes, detail, drill, panZoom, // pass attachPanZoom from pan-zoom-viewport.js
}) => void
  - const DETAIL
  - const ENGINE_DESIGN
  - const LANES_DESIGN
- `agent/skills/architecture-viz-studio/sample/diagrams/erd-diagram.js`
  - function buildErd: (erdBody, data, rels, opts) => void
  - function drawErdLines: (rels) => void
  - function initErd: ({...}, rels, drill, panZoom, intro, // caption above the grid (HTML) => void
  - const ERD
  - const ERD_RELS
- `agent/skills/architecture-viz-studio/sample/diagrams/overlay-lens-system.js` — function initOverlays: ({...}, overlays, reduced) => void, const OVERLAYS
- `agent/skills/architecture-viz-studio/sample/diagrams/pan-zoom-viewport.js` — function attachPanZoom: (opts) => void
- `agent/skills/atlassian-rest/scripts/confluence-format.mjs`
  - function markdownToStorage: (markdown) => void
  - function storageToMarkdown: (html) => void
  - function htmlInlineToMarkdown: (html) => void
  - function stripHtmlTags: (text) => void
- `agent/skills/bmad-auto/scripts/context-usage.py`
  - function claude_projects_dir: () -> Path
  - function iter_transcripts: () -> list[Path]
  - function find_transcript_by_session_id: (session_id) -> Optional[Path]
  - function find_transcript_by_agent: (agent_name, team_name) -> Optional[Path]
  - function parse_context_window: (model_identifier) -> Optional[int]
  - function parse_transcript: (transcript_path, agent_name) -> dict[str, Any]
  - _...4 more_
- `agent/skills/book-converter/scripts/analyze_structure.py`
  - function extract_headers: (raw_file) -> list[dict]
  - function detect_issues: (raw_file, sample_size) -> dict
  - function generate_structure_report: (project_dir) -> str
  - function main: ()
- `agent/skills/book-converter/scripts/convert_book.py`
  - function sanitize_name: (name) -> str
  - function setup_project_structure: (epub_path, base_dir) -> dict
  - function extract_epub_with_pandoc: (epub_path, output_dir) -> Path
  - function copy_formatting_standards: (project_dir, skill_dir)
  - function create_progress_file: (project_dir, book_name, raw_file)
  - function main: ()
- `agent/skills/book-converter/scripts/merge_book.py`
  - function extract_headers: (content) -> list[tuple[int, str, str]]
  - function fix_image_paths: (content, images_subdir) -> str
  - function load_chapter_map: (project_dir) -> list[dict]
  - function process_book: (project_dir, chapter_order) -> tuple[str, list[tuple[int, str, str]]]
  - function generate_toc: (headers, str, str]], book_title) -> str
  - function detect_book_title: (project_dir) -> str
  - _...1 more_
- `agent/skills/github-sync/scripts/parse-artifacts.py`
  - function extract_story_id: (filename) -> Optional[str]
  - function parse_frontmatter: (text) -> Dict[str, str]
  - function read_file: (path) -> str
  - function shorten_title: (title, max_len) -> str
  - function detect_synced: (first_line) -> Tuple[bool, Optional[str]]
  - function extract_status: (text) -> str
  - _...8 more_
- `agent/skills/jira-to-local/scripts/adf.mjs`
  - function adfToMarkdown: (node, mediaResolver, depth) => void
  - function adfToPlainText: (node) => void
  - function renderValue: (val, mediaResolver) => void
  - function parseDevelopment: (raw) => void
  - function formatSeconds: (secs) => void
  - function cell: (text) => void
- `agent/skills/jira-to-local/scripts/config.mjs`
  - function findConfigPath: (startDir) => void
  - function findWorkspaceRoot: (startDir) => void
  - function validateConfigFile: (path) => void
  - function loadConfig: ({...}) => void
  - function issueTypeConfig: (config, typeName) => void
  - function instructionsFor: (config, typeName) => void
  - _...3 more_
- `agent/skills/jira-to-local/scripts/confluence-format.mjs`
  - function storageToMarkdown: (html) => void
  - function htmlInlineToMarkdown: (html) => void
  - function stripHtmlTags: (text) => void
- `agent/skills/jira-to-local/scripts/dev-status.mjs` — function fetchDevStatus: (cred, issueId) => void, function groupByRepository: (dev) => void
- `agent/skills/jira-to-local/scripts/fetch-confluence.mjs` — function pageIdFromUrl: (url) => void
- `agent/skills/jira-to-local/scripts/jira-api.mjs`
  - function credentials: (config) => void
  - function connect: (options) => void
  - function apiGet: (cred, path) => void
  - function apiGetSoft: (cred, path) => void
  - function graphqlSoft: (cred, operationName, query, variables) => void
  - function getAllPages: (cred, path, key, {...}, soft) => void
  - _...1 more_
- `agent/skills/mcp-builder/scripts/connections.py`
  - function create_connection: (transport, command, args, env, str], url, headers, str]) -> MCPConnection
  - class MCPConnection
  - class MCPConnectionStdio
  - class MCPConnectionSSE
  - class MCPConnectionHTTP
- `agent/skills/mcp-builder/scripts/evaluation.py`
  - function parse_evaluation_file: (file_path) -> list[dict[str, Any]]
  - function extract_xml_content: (text, tag) -> str | None
  - function parse_headers: (header_list) -> dict[str, str]
  - function parse_env_vars: (env_list) -> dict[str, str]
  - function agent_loop: (client, model, question, tools, Any]], connection) -> tuple[str, dict[str, Any]]
  - function evaluate_single_task: (client, model, qa_pair, Any], tools, Any]], connection, task_index) -> dict[str, Any]
  - _...2 more_
- `agent/skills/skill-from-book/scripts/init-book-skill.py`
  - function create_skill_md: (skill_name, categories) -> str
  - function create_progress_md: (skill_name, categories) -> str
  - function create_guidelines_md: (skill_name, categories) -> str
  - function init_skill: (skill_name, output_path, categories) -> None
  - function main: ()
- `agent/skills/slide-maker/deck-template/scripts/lib/deck-driver.mjs`
  - function enterPresentMode: (page) => void
  - function makeDeckRequire: (deckDir) => void
  - function buildStandalone: (deckDir) => void
  - function serveDir: (dir, port) => void
  - function launchBrowser: (dep) => void
  - function openDeck: (url, {...}, width, height, scale) => void
  - _...6 more_
- `agent/skills/slide-maker/deck-template/scripts/lib/pptx-builders.mjs` — function buildOp: (op, ctx) => void
- `agent/skills/slide-maker/deck-template/scripts/lib/svg-to-custgeom.mjs` — function svgToCustomGeometryNodes: (icon, chipBox, h, AK, opts) => void, const COMPLEX_SVG_RE
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
- `apps/api/alembic/versions/0007_agents.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0008_workspace_settings.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/alembic/versions/0009_chat_entity_and_session_ref.py` — function upgrade: () -> None, function downgrade: () -> None
- `apps/api/src/agents/handlers/base.py`
  - class AgentRequest
  - class AgentContext
  - class AgentEvent
  - class AgentHandler
- `apps/api/src/agents/handlers/chat.py` — class ChatHandler
- `apps/api/src/agents/llm.py` — function stream_chat: (*, model, env, str], system_prompt, history, temperature, max_tokens, http, # injectable for tests) -> AsyncIterator[dict]
- `apps/api/src/agents/registry.py` — function register_handler: (handler) -> None, function get_handler: (entity_type) -> AgentHandler | None
- `apps/api/src/agents/runners/base.py`
  - class RunSpec
  - class RunHandle
  - class AgentEvent
  - class RunnerService
- `apps/api/src/agents/runners/factory.py` — function build_runner: () -> RunnerService
- `apps/api/src/agents/runners/local.py` — class LocalTmpRunner
- `apps/api/src/agents/runners/vercel.py` — class VercelSandboxRunner
- `apps/api/src/agents/sessions/store.py` — class SessionStore
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
  - function authenticate_websocket_token: (db, token) -> User | None
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
- `apps/api/src/models/agent.py` — class Agent
- `apps/api/src/models/api_key.py` — class ApiKey
- `apps/api/src/models/audit.py` — class AuditLogEntry
- `apps/api/src/models/conversation.py`
  - class Conversation
  - class ConversationParticipant
  - class Message
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
- `apps/api/src/models/user_profile.py` — class UserProfile
- `apps/api/src/models/workspace.py`
  - class User
  - class RefreshToken
  - class Workspace
  - class Role
  - class WorkspaceMember
- `apps/api/src/models/workspace_setting.py` — class WorkspaceSetting
- `apps/api/src/realtime/manager.py` — class ConnectionManager
- `apps/api/src/schemas/api.py`
  - class LoginRequest
  - class RegisterRequest
  - class TokenResponse
  - class RefreshRequest
  - class WorkspaceCreate
  - class WorkspaceUpdate
  - _...21 more_
- `apps/api/src/secrets/base.py` — class SecretRecord, class SecretStore
- `apps/api/src/secrets/db_store.py` — class DbSecretStore
- `apps/api/src/secrets/factory.py` — function build_secret_store: () -> SecretStore
- `apps/api/src/seed.py` — function main: () -> None
- `apps/api/src/services/agents.py`
  - class AgentError
  - class AgentNotFound
  - class AgentConflict
  - class AgentValidation
  - class AgentService
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
- `apps/api/src/services/notifications.py` — class NotificationSpec, class NotificationService
- `apps/api/src/services/profile_helpers.py`
  - function format_display_name: (first_name, last_name, fallback) -> str
  - function validate_custom_data: (data) -> None
  - function merge_custom_data: (existing, patch, is_put) -> dict
- `apps/api/src/services/profiles.py` — class ProfileService
- `apps/api/src/services/serializers.py`
  - function notification_to_dict: (n, *, workspace_name) -> dict
  - function user_to_dict: (u) -> dict
  - function workspace_to_dict: (w, *, role, permissions) -> dict
  - function profile_to_dict: (p) -> dict
  - function public_projection: (p) -> dict
- `apps/api/src/services/workspace_settings.py`
  - class WorkspaceSettingsError
  - class WorkspaceSettingsNotFound
  - class WorkspaceSettingsValidation
  - class WorkspaceSettingsService
- `apps/api/src/services/workspaces.py`
  - class WorkspaceError
  - class WorkspaceForbidden
  - class WorkspaceConflict
  - class WorkspaceService
- `apps/api/src/settings.py` — class Settings
- `apps/api/src/workflows/__init__.py` — function build_workflows: (registry, bus, connection_manager, cipher) -> None
- `apps/web/src/hooks/useProfile.ts`
  - function useProfile: () => void
  - function useUpdateProfile: () => void
  - function useExportProfile: () => void
  - function useDeleteAccount: () => void
- `apps/web/src/lib/avatar.ts`
  - function getInitials: (name) => string
  - function getInitialsFromNames: (firstName?, lastName?, fallbackName?) => string
  - function getAvatarSrc: (avatarUrl?) => string | undefined
  - function getAvatarData: (entity, fallbackEmailAsName) => void
  - function parseAvatarValue: (value?) => ParsedAvatar | null
  - type ParsedAvatar
  - _...1 more_
- `apps/web/src/lib/utils.ts` — function cn: (...inputs) => void, function oktaAdminConsoleFix: (value?) => string | null
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
  - _...19 more_
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
- `ATLASSIAN_API_TOKEN` **required** — agent/skills/atlassian-rest/scripts/confluence.mjs
- `ATLASSIAN_DOMAIN` **required** — agent/skills/atlassian-rest/scripts/confluence.mjs
- `ATLASSIAN_EMAIL` **required** — agent/skills/atlassian-rest/scripts/confluence.mjs
- `CORS_ORIGINS` (has default) — apps/api/.env.example
- `DATABASE_URL` **required** — apps/api/tests/conftest.py
- `DEBUG` (has default) — apps/api/.env.example
- `DEV` **required** — agent/skills/slide-maker/deck-template/src/App.jsx
- `DOCKER_HOST` (has default) — apps/api/tests/test_nats_integration.py
- `EMBEDDED_DB_DIR` **required** — apps/api/src/db/embedded.py
- `ENVIRONMENT` (has default) — apps/api/.env.example
- `EVENT_BUS_DRIVER` (has default) — apps/api/.env.example
- `FERNET_KEYS` (has default) — apps/api/.env.example
- `FRONTEND_URL` (has default) — apps/api/.env.example
- `GEMINI_API_KEY` (has default) — agent/skills/ai-multimodal/.env.example
- `GEMINI_IMAGE_GEN_MODEL` **required** — agent/skills/ai-multimodal/scripts/gemini_batch_process.py
- `GEMINI_MODEL` **required** — agent/skills/ai-multimodal/scripts/gemini_batch_process.py
- `IMAGE_GEN_MODEL` **required** — agent/skills/ai-multimodal/scripts/gemini_batch_process.py
- `JOBS_DEFAULT_TIMEOUT_SECONDS` (has default) — apps/api/.env.example
- `JOBS_RUN_RETENTION` (has default) — apps/api/.env.example
- `JOBS_SCHEDULER_TICK_SECONDS` (has default) — apps/api/.env.example
- `MULTIMODAL_MODEL` **required** — agent/skills/ai-multimodal/scripts/gemini_batch_process.py
- `NATS_URL` (has default) — apps/api/.env.example
- `OPENAI_BASE_URL` **required** — apps/api/src/agents/llm.py
- `REFRESH_TOKEN_EXPIRE_DAYS` (has default) — apps/api/.env.example
- `SECRET_ENCRYPT_VERSION` (has default) — apps/api/.env.example
- `SECRET_KEY` (has default) — apps/api/.env.example
- `SECRET_STORE_DRIVER` (has default) — apps/api/.env.example
- `SUPERADMIN_EMAIL` (has default) — apps/api/.env.example
- `VIDEO_GEN_MODEL` **required** — agent/skills/ai-multimodal/scripts/gemini_batch_process.py
- `VITE_API_URL` (has default) — apps/web/src/providers/dataProvider.ts
- `VITE_EDIT` **required** — agent/skills/slide-maker/deck-template/src/App.jsx
- `VITE_WS_URL` (has default) — apps/web/src/providers/liveProvider.ts

## Config Files

- `agent/skills/ai-multimodal/.env.example`
- `agent/skills/slide-maker/deck-template/tailwind.config.js`
- `agent/skills/slide-maker/deck-template/vite.config.js`
- `agent/skills/slides-generator/assets/template/tailwind.config.js`
- `agent/skills/slides-generator/assets/template/vite.config.js`
- `apps/api/.env.example`
- `apps/web/.env.example`
- `apps/web/tailwind.config.js`
- `apps/web/vite.config.ts`

---

# Middleware

## custom
- generate-status-report — `agent/skills/atlassian-rest/workflows/generate-status-report.md`
- slide-generate — `agent/skills/slide-maker/references/workflows/slide-generate.md`
- test-strategy — `agent/skills/typescript-clean-code/workflows/test-strategy.md`

## auth
- auth — `apps/api/src/services/auth.py`
- authProvider — `apps/web/src/providers/authProvider.ts`

---

# Dependency Graph

## Most Imported Files (change these carefully)

- `apps/api/src/db/session.py` — imported by **37** files
- `apps/web/src/types.ts` — imported by **23** files
- `apps/api/src/models/workspace.py` — imported by **22** files
- `apps/api/src/settings.py` — imported by **20** files
- `apps/api/src/events/bus.py` — imported by **18** files
- `apps/api/src/events/subjects.py` — imported by **15** files
- `apps/api/src/api/deps.py` — imported by **15** files
- `apps/api/src/core/permissions.py` — imported by **15** files
- `apps/api/tests/conftest.py` — imported by **15** files
- `apps/api/src/models/core.py` — imported by **13** files
- `apps/api/src/db/base.py` — imported by **12** files
- `apps/api/src/events/publisher.py` — imported by **12** files
- `apps/api/src/services/workspaces.py` — imported by **12** files
- `apps/api/src/core/dates.py` — imported by **12** files
- `apps/api/src/schemas/api.py` — imported by **11** files
- `apps/api/src/models/api_key.py` — imported by **10** files
- `apps/api/src/api/crud.py` — imported by **10** files
- `apps/api/src/models/conversation.py` — imported by **8** files
- `apps/api/src/services/serializers.py` — imported by **8** files
- `apps/api/src/models/jobs.py` — imported by **8** files

## Import Map (who imports what)

- `apps/api/src/db/session.py` ← `apps/api/src/agents/handlers/chat.py`, `apps/api/src/api/deps.py`, `apps/api/src/api/routes/agents.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/audit.py` +32 more
- `apps/web/src/types.ts` ← `apps/web/src/components/AppLayout.tsx`, `apps/web/src/components/AppLayout.tsx`, `apps/web/src/components/NotificationCenter.tsx`, `apps/web/src/contexts/WorkspaceContext.tsx`, `apps/web/src/hooks/useProfile.ts` +18 more
- `apps/api/src/models/workspace.py` ← `apps/api/src/api/deps.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/members.py`, `apps/api/src/api/routes/notifications.py` +17 more
- `apps/api/src/settings.py` ← `apps/api/alembic/env.py`, `apps/api/src/agents/handlers/chat.py`, `apps/api/src/agents/runners/factory.py`, `apps/api/src/agents/runners/local.py`, `apps/api/src/agents/sessions/store.py` +15 more
- `apps/api/src/events/bus.py` ← `apps/api/src/container.py`, `apps/api/src/events/factory.py`, `apps/api/src/events/inprocess.py`, `apps/api/src/events/nats.py`, `apps/api/src/events/publisher.py` +13 more
- `apps/api/src/events/subjects.py` ← `apps/api/src/agents/handlers/chat.py`, `apps/api/src/events/nats.py`, `apps/api/src/events/publisher.py`, `apps/api/src/services/agents.py`, `apps/api/src/services/api_keys.py` +10 more
- `apps/api/src/api/deps.py` ← `apps/api/src/api/routes/agents.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/auth.py`, `apps/api/src/api/routes/conversations.py` +10 more
- `apps/api/src/core/permissions.py` ← `apps/api/src/api/routes/agents.py`, `apps/api/src/api/routes/api_keys.py`, `apps/api/src/api/routes/audit.py`, `apps/api/src/api/routes/conversations.py`, `apps/api/src/api/routes/invitations.py` +10 more
- `apps/api/tests/conftest.py` ← `apps/api/tests/test_agents.py`, `apps/api/tests/test_api_key_security.py`, `apps/api/tests/test_api_keys.py`, `apps/api/tests/test_audit_workflow.py`, `apps/api/tests/test_auth.py` +10 more
- `apps/api/src/models/core.py` ← `apps/api/src/api/routes/invitations.py`, `apps/api/src/api/routes/notifications.py`, `apps/api/src/jobs/builtin.py`, `apps/api/src/models/__init__.py`, `apps/api/src/seed.py` +8 more

---

# Test Coverage

> **26%** of routes and models are covered by tests
> 27 test files found

## Covered Routes

- GET:
- POST:
- GET:/

## Covered Models

- Agent
- ApiKey
- AuditLogEntry
- Conversation
- ConversationParticipant
- Message
- Invitation
- Notification
- JobDefinition
- JobRun
- JobLogEntry
- StoredSecret
- UserProfile
- User
- RefreshToken
- Workspace
- Role
- WorkspaceMember

---

# Git Hooks

> **Note for agents:** These hooks fire automatically on git operations and will block the operation if they fail.

## `pre-commit` — raw git hook

- **npx**: `npx codesight --wiki -o .codesight`
- **git**: `git add .codesight/`

_Source: .git/hooks/pre-commit_

---

_Generated by [codesight](https://github.com/Houseofmvps/codesight) — see your codebase clearly_