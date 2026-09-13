# Inbox Messaging Upgrade — Detailed Implementation Plan

**Branch:** `feat/inbox-messaging` (cut from `main` @ `66415bc`)  
**Status:** Awaiting approval — no code yet  
**Stack:** FastAPI + SQLAlchemy, Refine v5 + `dataProvider`/`liveProvider`, shadcn/ui, Tiptap  
**Author:** Amelia (bmad-agent-dev) — 2026-08-28  
**Updates:** v2 incorporating review feedback (permissions, agents, workspace scoping, archiving, search, title editing, Tiptap)

---

## 0. How to read this plan

- File paths use `path:line` style so you can jump directly, e.g. `apps/api/src/models/core.py:29`.
- "Current pattern" means we reuse an existing idiom verbatim; "New" means new file or table.
- Every story is test-first (red → green → refactor) on `feat/inbox-messaging`.

---

## 1. Target UX (approved)

| Area | Behaviour |
|---|---|
| **Inbox** | `/inbox` becomes a tabbed split view: left = list, right = detail. Tabs: `Messages` \| `Notifications` (scalable for future tabs). |
| **Messages left pane** | Conversation rows: participant avatars/names (you excluded), title (subject), last-message preview, timestamp, unread dot + count. Sorted `last_message_at DESC`. Filters: Archive toggle (Active ↔ Archived), Search box (title / participant / preview). |
| **Messages right pane** | Thread header: editable title, participant chips, Archive / Unarchive button. Body: chat bubbles (right = own messages, left = others) showing sender `display_name`, avatar fallback, timestamp, markdown-rendered body (`react-markdown` already at `InboxPage.tsx:3`). Footer: Tiptap rich editor + Send. Replaces old `Mark as read / Open link` at `InboxPage.tsx:283`. |
| **Compose** | `Compose` button above list opens a **dialog** (not a Refine `CreateView` page — exception approved). Fields: Title (optional, defaults to derived `"Chat with A, B"` or first message excerpt), Participants multi-select (workspace members only, `GET /members` `apps/api/src/api/routes/members.py:50`), Initial message (Tiptap). Participants 1..19 others + self = 2..20 limit, de-duplicated. On success the new conversation is selected and dialog closes. |
| **Title editing** | Inline pencil in thread header; `PATCH /conversations/{id}`; helper `ConversationService.rename()` callable from future agent code. |
| **Archive** | Per-user `archived_at` on participant row. Active list hides archived; toggle `Show archived` flips filter. Archiving does **not** affect other participants. Manual only — reading never hides. Small `Archive` button in header + row hover action. |
| **Notifications tab** | Keeps `ListView`/`Table` feel but now **workspace-scoped only** (see §6). Bell `NotificationCenter.tsx:28` still shows unread notifications including `type=conversation_message` pointers. Clicking a message-type notification deep-links to `Messages` tab and opens that conversation. |
| **Notifications vs Messages** | A new message appends to its thread row (no new row). A `Notification` pointer row (`type=conversation_message`) is still created for each other participant so the bell badge and notification list surface the event via the existing realtime path. See §5. |

---

## 2. Principle & Pattern Alignment

- **Service layer over routes:** `WorkspaceService:32`, `NotificationService:18` pattern — thin routes, domain in `src/services/*`.
- **Events over direct DB fan-out:** Use `src/events/subjects.py:9`, `src/workflows/__init__.py:57` bus, `SessionFactory` per workflow consumer.
- **Workspace-scoped auth:** `get_current_workspace_id` + `resolve_auth_principal` + `require_key_permission` at `src/api/deps.py:111`. Users always pass; API keys gated on their own permission list.
- **Frontend canonical exceptions:** `AGENTS.md` says Refine `create` must be a page — Compose dialog is the one approved exception because it seeds a conversation with an initial message atomically.
- **Tiptap:** Markdown-first storage; Tiptap is only the editor. Rendering stays `react-markdown` for consistency and XSS safety.

---

## 3. Domain Model (new tables)

Create `apps/api/src/models/conversation.py` — imported via `src/models/__init__.py:13` barrel.

### 3.1 `conversations`

| Column | Type | Notes |
|---|---|---|
| `id` | `StringUUID` PK `Base.id` | `src/db/base.py:12` |
| `workspace_id` | `StringUUID` idx | FK `workspaces.id`, NOT NULL |
| `created_by_user_id` | `StringUUID` idx | creator |
| `title` | `String(300)` nullable | Subject / session title. Auto-derived if blank: `"Chat with {other names}"` or truncated first message. Editable. |
| `last_message_at` | `DateTime(tz)` nullable | Denormalised for sorting; updated in same tx as message |
| `last_message_preview` | `String(200)` nullable | Truncated plain-text of last message |
| `created_at`, `updated_at` | via `TimestampMixin` | `src/db/base.py:50` |

### 3.2 `conversation_participants` — **polymorphic, agent-ready**

| Column | Type | Notes |
|---|---|---|
| `id` | `StringUUID` PK | |
| `conversation_id` | `StringUUID` idx FK `conversations.id` CASCADE | |
| `participant_type` | `String(10)` default `"user"` | Enum `user\|agent`. Only `user` used in v1. |
| `participant_id` | `StringUUID` idx | For `user` → `users.id`; for `agent` → future `agents.id`. |
| `user_id` | `StringUUID` nullable FK `users.id` | Convenience FK for v1; kept in sync with `participant_id` when type=user. Allows indexed join without generic cast. Nullable to allow future `agent` rows without migration. Check: `(participant_type='user' AND user_id IS NOT NULL)` OR `(participant_type='agent' AND agent_id IS NOT NULL)`. |
| `agent_id` | `StringUUID` nullable | No FK until `agents` table exists. |
| `joined_at` | `DateTime(tz)` | |
| `last_read_at` | `DateTime(tz)` nullable | For unread calc |
| `last_read_message_id` | `StringUUID` nullable FK `messages.id` | |
| `archived_at` | `DateTime(tz)` nullable | Per-user archive; `NULL` = active. Toggle via endpoint. |
| `created_at`, `updated_at` | mixin | |

Indices: `UQ(participant_type, conversation_id, participant_id)`, `IX(conversation_id)`, `IX(participant_type, participant_id)`, `IX(workspace via join)` not needed directly.

Constraint rationale: dual-column (`user_id`/`agent_id`) + generic (`participant_type`/`participant_id`) keeps strong FK for users today and zero-migration agent support tomorrow. ORM exposes `participant_type`/`participant_id` as canonical; `user_id`/`agent_id` are storage helpers.

### 3.3 `messages`

| Column | Type | Notes |
|---|---|---|
| `id` | `StringUUID` PK | |
| `conversation_id` | `StringUUID` idx FK CASCADE | |
| `sender_type` | `String(10)` default `"user"` | `user\|agent` quake-proof: agents will use `agent`. |
| `sender_id` | `StringUUID` idx | |
| `sender_user_id` | `StringUUID` nullable FK `users.id` | Mirrors `sender_id` when `sender_type=user`. |
| `sender_agent_id` | `StringUUID` nullable | Placeholder |
| `body` | `Text` | Markdown source, 1..5000 chars (validated in schema). Produced by Tiptap (see §8). |
| `body_html` | `Text` nullable | Optional cached HTML render; not indexed. Store only markdown canonically; render on read via `react-markdown`. |
| `created_at`, `updated_at` | mixin | `created_at` is authoritative send time; `updated_at` unused. |

Index: `IX(conversation_id, created_at)`.

### 3.4 `notifications` (no schema change)

Add a new `type = "conversation_message"` pointer row. `payload` shape: `{"conversation_id": str, "message_id": str, "sender_id": str, "sender_name": str, "workspace_id": str}`. Existing `notifications` index usage unchanged (`apps/api/alembic/versions/0001_initial.py:118`).

### 3.5 Migration

File `apps/api/alembic/versions/0005_conversations.py`:

```python
revision = "0005"
down_revision = "0004"
```

Steps: create `conversations`, `conversation_participants`, `messages`; indices above; Alembic `upgrade`/`downgrade` drops in reverse order. Ensure dialect branch on `postgresql` UUID vs `String(36)` like `0001_initial.py:26`.

---

## 4. Permissions

### 4.1 Users vs API keys

**Decision confirmed:** Session users **always** have `notification:read`, `notification:acknowledge`, `message:read`, `message:send` regardless of `Role.permissions` at `src/core/permissions.py:20`. Only **API keys** are gated on the key's permission list.

Implementation: reuse `require_key_permission` idiom at `src/api/deps.py:111`:

```python
# New constants
MESSAGE_READ = "message:read"
MESSAGE_SEND = "message:send"
# (optionally: MESSAGE_CREATE aliases MESSAGE_SEND)
```

Routes for conversations/messages/notifications **must use `require_key_permission`**, NOT `require_permission`. Example:

```python
@router.get("", dependencies=[Depends(require_key_permission(MESSAGE_READ))])
```

`require_permission` stays for truly role-gated resources (`members`, `roles`, `workspace:update`). `accessControlProvider.ts:8` `PERMISSION_MAP` for `conversations`/`messages` is still added for **API-key-driven UI** cases (when the frontend is driven by an API key's preview), but for normal user login `can` returns `true` unconditionally for those resources. Simplest: in `accessControlProvider.ts:48` add a branch:

```typescript
if (resource === "conversations" || resource === "messages" || resource === "notifications") return { can: true };
```

Alternatively map to `message:read` etc. but bypass role check when `principal.api_key == null`. Document as comment.

### 4.2 Permission catalog update `src/core/permissions.py:26`

```python
MESSAGE_READ = "message:read"
MESSAGE_SEND = "message:send"
ALL_PERMISSIONS = [..., MESSAGE_READ, MESSAGE_SEND]
# permissions_for_role: every system role gets both (owner/admin/editor/viewer),
# so `sync_system_role_permissions` converges existing workspaces.
```

### 4.3 Key minting `src/schemas/api.py:56` `ApiKeyCreate`

`permissions` list now validates against `ALL_PERMISSIONS` including the two new values (existing `validate` already clamps to catalog). Keys minted without `message:read` cannot `GET /conversations`.

---

## 5. Event-driven Notification Synthesis

### 5.1 New subjects `src/events/subjects.py:9`

```python
CONVERSATION_MESSAGE_CREATED = "conversations.message.created"
CONVERSATION_CREATED = "conversations.created"  # optional audit
CONVERSATIONS = "conversations"
```

Update `TRANSIENT_SUBJECTS` — keep `notifications.created` transient only; `conversations.message.created` is **durable** (needs persistence so offline replicas don't lose the notification-creation side effect). Its publisher (`ConversationService.send_message`) publishes durable (default `transient=False`).

### 5.2 Workflow handlers `src/workflows/__init__.py:62`

```python
async def on_conversation_message(payload, metadata):
    # payload: {workspace_id, conversation_id, message_id, sender_id, sender_type, sender_name, body_preview, participant_user_ids}
    async with SessionFactory() as s:
        # 1. For each participant_user_id != sender, create Notification pointer
        for uid in payload["participant_user_ids"]:
            if uid == payload["sender_id"] and payload["sender_type"] == "user": continue
            await NotificationService(s, bus).create(
                user_id=uid, workspace_id=payload["workspace_id"],
                type="conversation_message",
                title=payload.get("title") or f"New message in {payload['workspace_name']}",
                body=payload["body_preview"],
                metadata={...}, correlation_id=metadata.correlation_id)
        # 2. Bump `conversations.last_message_at/preview` is already done in service tx; no-op here
    # 3. Transient fan-out: push realtime to each participant's WS sessions
    for uid in payload["participant_user_ids"]:
        await connection_manager.push(uid, {"event":"message.created","data":payload}, event="message.created")

async def on_conversation_created(...): # audit only
```

Registration:

```python
registry.register(Subjects.CONVERSATION_MESSAGE_CREATED, on_conversation_message)  # durable
registry.register(Subjects.NOTIFICATIONS_CREATED, on_notification_created, fanout=True) # existing
# Fanout push for live thread also wired: separate transient handler or inline push after commit in service
```

**Why two pushes?** `on_notification_created` already pushes `notification.created` to WS (covers bell). The new `message.created` push carries the raw message so the thread can append without refetch even if the notification is acknowledged.

### 5.3 Audit

`publish_audit` for `conversation.created` and `message.created` like `WorkspaceService:90`.

---

## 6. Workspace Scoping — Breaking Change

### 6.1 Current vs Desired

| Route | Today (`apps/api/src/api/routes/notifications.py:60`, `69`, `107`) | After |
|---|---|---|
| `GET /notifications` | `get_optional_workspace_id`; API keys filtered, session users see **all workspaces** | `get_current_workspace_id` **required**; always filtered to `workspace_id == header` |
| `GET /notifications/unread-count` | same | same |
| `PATCH/DELETE /notifications/{id}` | optional | optional but enforce `workspace_id == header` when provided |
| `GET /conversations`, `GET /conversations/{id}/messages`, etc. | — (new) | **required** `X-Workspace-ID`; every query `WHERE workspace_id == header` and `participant is me` |
| Future `GET /invitations`, etc. | — | keep as-is; this plan does not change invitations |

### 6.2 Implications

- **Frontend:** `InboxPage.tsx:62` `workspaceFilterOptions` + `workspaceFilter` Select + cross-workspace buckets at `InboxPage.tsx:77` (`currentWs` vs `otherWs`) are **deleted**. Inbox tabs now show only current workspace; switching workspace via `WorkspaceSwitcher` (`AppLayout.tsx:97`) already remounts via `WorkspaceContext.tsx:72` `queryClient.removeQueries`, so counts refetch automatically. Update `dataProvider.ts:40` already injects `workspaceStore.get()` header — no change needed.
- **Tests:** Existing notification tests that call without header will 400; add `X-Workspace-ID` in `conftest` helpers.
- **Migration for users:** Clients without header will get `400 X-Workspace-ID header is required` — acceptable, mirrors `members`/`roles` behaviour.

---

## 7. Backend API Contract

All prefixes `API = "/api/v1"` at `src/main.py:90`.

### 7.1 Schemas `src/schemas/api.py:60`

```python
class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    participant_user_ids: list[str] = Field(min_length=1, max_length=19) # others only; self added server-side
    initial_message: str = Field(min_length=1, max_length=5000) # markdown

class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)

class ConversationArchive(BaseModel):
    archived: bool

class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)

class ConversationRead(BaseModel):
    last_read_message_id: str | None = None # optional; defaults to latest
```

### 7.2 Routes `src/api/routes/conversations.py` (new file)

```python
router = APIRouter(prefix="/conversations", tags=["conversations"])
```

| Method | Path | Perm (key) | Request | Response | Notes |
|---|---|---|---|---|---|
| `GET ""` | list my conversations | `message:read` (key) | `?archived=true\|false|null` (default false), `?q=...`, standard `parse_query` pagination (`limit, offset, sort=last_message_at:desc`), `X-Workspace-ID` required | `200 [{id, workspace_id, title, created_by_user_id, last_message_at, last_message_preview, unread_count, is_archived, participants:[{type,id,display_name,avatar_url}], message_count}]` + `X-Total-Count` | `unread_count` = count messages `created_at > participant.last_read_at` (or 0 if never read). `is_archived` = `participant.archived_at IS NOT NULL` for current principal. Search: `ILIKE %q%` on `title` OR participant display_name OR `last_message_preview`. |
| `POST ""` | create convo + first message (atomic) | `message:send` | `ConversationCreate` | `201 {conversation, first_message}` | Validates each `participant_user_id` is active `WorkspaceMember` in header workspace; dedup; include `user.id` as participant even if not listed; enforce 2..20 total distinct `user` participants; derive `title` if absent; insert conversation, participants, message, set preview, commit, publish `conversations.message.created` + audit. |
| `GET "/{conversation_id}"` | get one | `message:read` | — | `200 {conversation with participants, unread_count}` | 403 if not participant, 404 if workspace mismatch |
| `PATCH "/{conversation_id}"` | rename | `message:send` (key) but really participant check | `ConversationUpdate` | `200 {conversation}` | Must be participant; validates title, updates `conversations.title` + audit `conversation.renamed`. Helper for agents: `ConversationService.rename(conversation_id, title, actor_type, actor_id)` (see §7.4) |
| `PATCH "/{conversation_id}/read"` | mark read | `message:read` | `ConversationRead` | `204` or `200 {participant}` | Sets `participant.last_read_at = now()`, `last_read_message_id = body.last_read_message_id ?? latest message id in conversation`. |
| `PATCH "/{conversation_id}/archive"` | toggle archive | `message:read` | `ConversationArchive` | `200 {archived}` | Sets `participant.archived_at = now()` or `NULL`. Per-user only. |
| `GET "/{conversation_id}/messages"` | list messages | `message:read` | `?limit,offset,sort=created_at:asc` | `200 [{id, conversation_id, sender_type, sender_id, sender_name, body, created_at}]` + `X-Total-Count` | Participant check; fixed `sortable={"created_at"}`, `filterable={}`. |
| `POST "/{conversation_id}/messages"` | send | `message:send` | `MessageCreate` | `201 {message}` | Participant check; insert, bump conversation preview, publish durable event, create notification pointers via workflow, audit. |
| `GET "/unread-count"` | dedicated count | `message:read` (key) | — | `200 {count: int, unread_conversations: int}` | `count` = sum `unread_count` across active conversations; `unread_conversations` = distinct conversations with `unread_count>0`. Workspace-scoped. |

All handlers use `get_current_user`, `resolve_auth_principal`, `require_key_permission(...)`, `get_current_workspace_id`, `get_db`, `get_container` matching `notifications.py:60` style. Errors: `400` bad participants/title, `403` not participant/ wrong workspace, `404` unknown id.

### 7.3 Unread-count for notifications (dedicated already exists, now scoped)

`GET /notifications/unread-count` at `notifications.py:91` already exists — change to `get_current_workspace_id` required and delegate to `SELECT COUNT(*) WHERE user_id==me AND workspace_id==header AND acknowledged_at IS NULL`. Document that bell badge = `notification unread + conversation unread` or unified? Proposal: keep two separate GETs, frontend sums: `bellCount = notifCount + convUnreadConversations` (display as single badge) or two badges. Easiest: badge = `max(notifCount, convUnread)` not correct. Specify: badge = `notifCount + convUnreadConversations` (distinct conversations with unread). Call both endpoints in `NotificationCenter` + `Inbox` and merge.

### 7.4 Agent helper (title editing from code)

```python
class ConversationService:
    async def rename(self, conversation_id: str, title: str,
                     *, actor_user_id: str | None = None,
                     actor_agent_id: str | None = None,
                     actor_type: Literal["user","agent"] = "user") -> Conversation: ...
    # Future agent type will be `actor_agent_id` + type="agent".
    # Collaborative: validates title, checks workspace, checks actor is participant (for user) or agent-allowlist (for agent).
    # Publishes `conversation.renamed` event for live title update (optional fanout).
```

Expose via same `PATCH` route; the helper is the service method agents import directly, not an HTTP endpoint for agents (agents are internal). Document that `title` edit is participant-scoped and immediate.

---

## 8. Frontend

### 8.1 Dependencies

```bash
# in apps/web
npm i @tiptap/react @tiptap/pm @tiptap/starter-kit @tiptap/extension-placeholder @tiptap/extension-link
npm i tiptap-markdown  # or @tiptap/markdown — evaluate; fallback: custom serializer HTML→markdown via `turndown`
```

Tiptap is ProseMirror-based; bundle impact ~120kb gzipped. Keep `react-markdown` for rendering.

### 8.2 Types `apps/web/src/types.ts:65`

```typescript
export type Conversation = {
  id: string;
  workspace_id: string;
  title: string | null;
  created_by_user_id: string;
  last_message_at: string | null;
  last_message_preview: string | null;
  unread_count: number;
  is_archived: boolean;
  participants: Array<{
    type: "user" | "agent";
    id: string;
    display_name: string;
    avatar_url?: string | null;
  }>;
  message_count?: number;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: string;
  conversation_id: string;
  sender_type: "user" | "agent";
  sender_id: string;
  sender_name: string;
  sender_avatar_url?: string | null;
  body: string; // markdown
  body_html?: string | null;
  created_at: string;
};

export type Notification = {
  // existing ... + payload discriminant now includes:
  // payload: { conversation_id?: string; message_id?: string; ... }
  // type: "conversation_message" | ...
};
```

### 8.3 Routing & Resources `apps/web/src/App.tsx:43`

```typescript
resources={[
  // ...existing
  { name: "notifications", list: "/inbox", meta:{ label:"Inbox" } },
  { name: "conversations", list: "/inbox" }, // sub-resource, no separate entry
  { name: "messages", list: "/inbox" },
]}
```

Keep single nav item `Inbox`. Tabs inside `InboxPage` drive which `resource` query is active.

### 8.4 InboxPage overhaul `apps/web/src/pages/InboxPage.tsx:1`

**File breakdown (refactor into sub-components under `apps/web/src/components/inbox/`):**

- `InboxPage.tsx` — shell: header, tab state (`useState<"messages"|"notifications">`), workspace guard via `useWorkspace`, compose dialog trigger.
- `MessageList.tsx` — left pane: `useList<Conversation>({resource:"conversations", pagination, filters:[{field:"archived",...},{field:"q",...}] filters built from toggle+search; sorters:[{field:"last_message_at",order:"desc"}]}})`; renders virtual list or simple map (200 cap). Row: `cn(active)` pattern like current. Archive hover action `Archive`/`Unarchive`.
- `ThreadView.tsx` — right pane when `selectedConversationId != null`: header with editable title (inline `Input` + Save/Cancel, `useUpdate({resource:"conversations", id, values:{title}})`), participant chips (`Avatar`), Archive button, message list (`useList<Message>` filtered by `conversation_id`, sortable `created_at:asc`, pageSize 100), auto-scroll, markdown bubbles (`<Markdown>{body}</Markdown>`), Tiptap editor footer.
- `NotificationList.tsx` — extracted from old `InboxPage` left+right, now rendered under `Notifications` tab.
- `ComposeDialog.tsx` — `Dialog` with `react-hook-form` + `zodResolver`, fields `title`, `participants: string[]` (multi-select `Command`+`Popover` loading `useList<Member>`), `initial_message` (Tiptap controlled). Submit: `useCreate({resource:"conversations", values})` mapping to `ConversationCreate`; on success `query.invalidate`, select new id, close dialog.
- `TiptapEditor.tsx` — wrapper: `useEditor({extensions:[StarterKit, Link, Placeholder], content})`, exports `getMarkdown()`. For now, persist `editor.getHTML()` converted to markdown via `turndown` or `tiptap-markdown` `editor.storage.markdown.getMarkdown()`. Keep toolbar minimal: Bold, Italic, Link, Code, Bullet/Ordered list — shadcn `Toggle` group.

**Left pane header actions:**

```
[Compose]  [Search input with debounce 300ms]  [Toggle: Active | Archived]
```

Search: local state `q`, debounced into `useList` filter `field:"q", operator:"contains", value: q`. Backend does `ILIKE` (see §7.2).

**Right pane chat footer:**

```
<TiptapEditor value={draft} onChange={setDraft} placeholder="Write a message…" />
<Button onClick={send} disabled={!draft || sending}><SendHorizonal /></Button>
```

`send`: `useCreate({resource:"messages", values:{body: markdown}})` or `useCustomMutation` to `POST /conversations/{id}/messages`. Optimistic append: prepend local message with temp id, replace on success. Also `useCustomMutation({url:`conversations/${id}/read`, method:"patch"})` on open and after send.

**Live updates:** extend `liveProvider.ts:23` to also forward `message.created` and `conversation.renamed`/`archived`:

```typescript
if (message.event === "message.created") {
  const cid = message.data?.conversation_id;
  // invalidate both the conversation's messages and the conversation list
  callbacks.get("resources/conversations")?.forEach(cb => cb({type:"updated", payload:{ids:[cid], data:message.data}}));
  callbacks.get(`resources/conversations/${cid}/messages`)?.forEach(...);
}
if (message.event === "conversation.renamed") { ... }
```

Also keep `notification.created` path for bell.

**Access:** Compose button gated on `canCreate`? Per §4.1, users always can — so button always enabled for session users. API-key preview path still respects `useCan`.

### 8.5 NotificationCenter `apps/web/src/components/NotificationCenter.tsx:28`

- Branch on `n.type === "conversation_message"`: render `"New message in {title}"`, preview `n.body`, `n.payload.sender_name`, timestamp; click -> `navigate("/inbox?tab=messages&conversationId={payload.conversation_id}")` + `setWorkspace` if needed (reuse `canOpen` logic but workspace is now always current, so simplified).
- Bell badge: fetch both `GET /notifications/unread-count` and `GET /conversations/unread-count` (two `useCustom` queries), sum distinct unread conversations + notification count for number displayed. Keep sheet grouping per workspace deleted.

### 8.6 AppLayout

No change needed besides ensuring `X-Workspace-ID` header always sent. `SidebarNav` keeps `Inbox` at `MENU_ITEMS:60` already `notification:read`; after permission relaxation the item remains visible.

---

## 9. Search, Archive, Title — Detailed

### Search
- Client: input at top of left pane, `debounce 300ms`, pushes `q` into `useList` filters. Backend `GET /conversations?q=foo` does `WHERE (title ILIKE %q% OR last_message_preview ILIKE %q% OR EXISTS (SELECT 1 FROM users WHERE id=participant.user_id AND display_name ILIKE %q% AND participant.conversation_id=...))` — two queries: first filter conversations via `IN (SELECT ...)`. Use parameterized `select` with `or_`.
- No full-text index in v1; sufficient for <20k conversations per workspace. Add `GIN` later if needed.

### Archive
- UI: toggle `Switch` or segmented control `Active | Archived` in `InboxPage` header. Default `Active`. When `archived=true`, the list query adds `filter.archived=true`. Row shows `Unarchive` action instead of `Archive`. Right pane header also has `Archive/Unarchive` button toggling via `PATCH /conversations/{id}/archive` (`useUpdate` with `archived` field).
- Behaviour: reading does not archive; archived conversation keeps unread count but is not shown in Active filter. Unarchiving is symmetric; new message **unarchives automatically** for recipient? Decision: **No auto-unarchive in v1** to keep explicit; recipient who archived will still get notification pointer but conversation stays in Archived until they toggle. Revisit if users expect auto.

### Title editing
- Inline: header shows `<h3>{conversation.title ?? "Untitled"}</h3>` + pencil `Button ghost size="icon"`; click replaces with `<Input value={editTitle} onChange />` + Save/Cancel. Save via `useUpdate({resource:"conversations", id, values:{title: editTitle}})`.
- Helper for agents: `await conversation_service.rename(cid, "New session", actor_agent_id=..., actor_type="agent")` — no permission beyond being a logical participant (future agents) or system caller; enforce length 1..300.
- Derived title fallback: if `title IS NULL` at creation, backend composes `"Chat with {other display_names}"` (limit 3 + `+N`). Subsequent `PATCH` can set explicit.

---

## 10. Tiptap → Markdown Contract

- **Store:** `messages.body` is canonical **markdown** string. Validation: `1..5000` chars, trim.
- **Write path:** `TiptapEditor` with `StarterKit` (Bold, Italic, Strike, Code, CodeBlock, BulletList, OrderedList, Link, Blockquote). Toolbar minimal 6 buttons. Extension `Markdown` if `tiptap-markdown` is stable; otherwise convert `editor.getHTML()` → markdown via `turndown` (already used elsewhere) on submit: `turndownService.turndown(html)`. Keep HTML cache `body_html` optional.
- **Read path:** `react-markdown` at `InboxPage.tsx:281` already installed (`package.json:43`). Bubbles render `{message.body}` via `<Markdown>{body}</Markdown>` with `prose prose-sm dark:prose-invert` wrapper and `break-words`.
- **Migration from plain text:** no-op — existing text is valid markdown.
- **Security:** `react-markdown` escapes raw HTML; Tiptap HTML is sanitized by `turndown` + markdown render path.

---

## 11. API / Data Layer Choices

- **Pagination:** reuse `parse_query` / `apply_query` / `X-Total-Count` at `notifications.py:82` / `members.py:64`. Keep `limit` default 50 for messages, 20 for conversations.
- **Custom dataProvider path:** keep `API_URL = "/api/v1"` `dataProvider.ts:10`. Relative `custom` resolver at `dataProvider.ts:128` supports `useCustom({url:"conversations/unread-count"})`.
- **Live mode:** `Refine options liveMode:"auto"` already at `App.tsx:40`; per-resource `liveProvider` invalidation covers thread append.
- **Error surfaces:** `enrichErrorMessage` `dataProvider.ts:79` already surfaces FastAPI `detail` as `error.message` — no extra toast handling.

---

## 12. Security & Compliance

- Participant validation via `WorkspaceService.get_membership` before every join; reject if any participant not `active`.
- No cross-workspace query: every SQL includes `conversations.workspace_id == :wid`.
- Rate limiting: `body` length + 20 participants max; abuse vector of rapid message spam mitigated by audit log but not blocked v1 — add TODO for token bucket if needed.
- XSS: markdown rendering only, no `dangerouslySetInnerHTML` path.
- Audit: `audit.entry.created` durable stream already via `workflows/__init__.py:225`.
- API keys: simulated "login as key" tests reuse `test_api_key_security.py` patterns — keys without `message:read` get `403 missing permission`.

---

## 13. Testing Plan

### 13.1 Backend (`apps/api/tests/`)

**New file `test_conversations.py`** — follows `conftest.py:75` `register_user`/`create_workspace` helpers and `test_member_event_workflows.py:18` `_wait_for` for bus.

| Test | Assertion |
|---|---|
| `test_create_conversation_success` | Two users in ws, A creates convo with B + title + initial msg -> 201, returns `conversation.title == input`, participants length 2, `last_message_preview`, `message` persisted |
| `test_create_rejects_non_member` | Participant email outside workspace -> 400 detail contains "not a member" |
| `test_create_enforces_workspace_scoping` | Try to include user from other workspace id but x-header=ws1 -> 400 |
| `test_list_requires_workspace` | `GET /conversations` without header -> 400 |
| `test_list_only_current_workspace` | Create convo in ws1 and ws2, list with ws1 header only returns ws1 |
| `test_send_and_list_messages` | `POST /conversations/{id}/messages` 201, `GET /.../messages?sort=created_at:asc` returns in order |
| `test_non_participant_forbidden` | Third user in ws tries to GET or POST -> 403 |
| `test_mark_read_clears_unread` | B has `unread_count>0`, PATCH read -> `unread_count==0` persists per-participant |
| `test_archive_toggle` | `PATCH .../archive {archived:true}` hides from `archived=false` list, appears in `archived=true`; unarchive reverse |
| `test_title_patch` | `PATCH /conversations/{id} {title:"New"}` 200 updates; helper `rename` via service call also works |
| `test_title_from_agent_helper` | call `ConversationService.rename(..., actor_type="agent", actor_agent_id="...")` updates title |
| `test_search_by_title_and_preview` | Create convo titles "Sprint", send msg "hello mars", GET `?q=mars` returns it, `?q=sprint` returns too |
| `test_search_by_participant_name` | q=display_name substring matches participant |
| `test_message_creates_notification_pointer_and_ws` | After send, `NOTIFICATION` row exists for B `type=conversation_message`; `_wait_for` on `Notification` count; plus `_wait_for` bus delivers `notification.created` (existing handler) |
| `test_api_key_without_perm_forbidden` | Mint key without `message:read` -> `GET /conversations` 403; mint with perm -> 200 |
| `test_api_key_with_perm_works` | |
| `test_polymorphic_agent_row_future` | Insert participant with `participant_type=agent` raw SQL succeeds and is returnable |

**Modify existing `test_notifications` (to be created if missing):** add case `test_notification_list_requires_workspace` expecting 400 without header, and `test_notification_not_leaking_cross_workspace`.

### 13.2 Frontend

- `apps/web` type-check: `npm run build` (`tsc --noEmit && vite build`) must pass.
- Manual QA checklist: compose -> send -> other browser tab receives WS instantly; archive toggle; search; title edit persists after reload; bell badge increments; switching workspace via `WorkspaceSwitcher` resets list to that workspace only.
- Optional: Playwright smoke at `apps/web/e2e` (not required v1).

---

## 14. Execution Order (stories)

| # | Story | Scope | Gate |
|---|---|---|---|
| **S1** | **Models + migration 0005** | `models/conversation.py`, `models/__init__.py`, `alembic/versions/0005*`, `settings` no-op | `alembic upgrade head` on fresh DB succeeds |
| **S2** | **Permission catalog + deps docs** | `core/permissions.py` add `MESSAGE_READ/ SEND`, `services/workspaces sync`, `providers/accessControlProvider` bypass for users, `schemas/api.py` DTOs | Existing tests still pass |
| **S3** | **ConversationService + routes + unread-count** | `services/conversations.py`, `api/routes/conversations.py`, `main.py` include, `POST/GET/PATCH` inc. title/archive/read/unread | `test_conversations` (minus bus) green |
| **S4** | **Bus subjects + workflows + WS fanout** | `events/subjects.py`, `workflows/__init__.py` handlers, `ConnectionManager` optional new path, notification pointer creation | `test_message_creates_notification_pointer_and_ws` green with `_wait_for` |
| **S5** | **Workspace-scoping retrofit for notifications** | `api/routes/notifications.py` change to `get_current_workspace_id`, remove cross-ws buckets, `InboxPage` filter removal, `NotificationCenter` grouping removal | Notification tests updated & green |
| **S6** | **Types + data layer + liveProvider** | `web/src/types.ts`, `web/src/providers/liveProvider.ts` (message.created), `web/src/providers/accessControlProvider.ts` | `npm run build` passes |
| **S7** | **Inbox UI Messages tab + Tiptap + Compose dialog + Archive + Search + Title** | `components/inbox/*`, `pages/InboxPage.tsx` refactor, `TiptapEditor.tsx`, `ComposeDialog.tsx` | Manual QA + `npm run build` |
| **S8** | **NotificationCenter message-type + deep-link + badge sum** | `components/NotificationCenter.tsx` branches, unread sum | Badge reflects both sources |
| **S9** | **Polish + docs + e2e** | empty/loading states, responsive, audit, README notes | Final verification |

Stories S2 and S1 parallelisable; S3 blocking S4; S5 independent of S3/S4 but coordinate header change; S6 blocking S7/S8.

---

## 15. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Cross-workspace notification retrofit breaks external API clients | 400 for missing header | Semver bump; document in migration notes; add `X-Workspace-ID` to client docs. Provide fallback 기간? — decided hard cut. |
| Tiptap bundle bloat | slower first paint | Lazy-load `TiptapEditor` via `React.lazy` on dialog/thread open. |
| Polymorphic generic FK weakens DB integrity | orphan participants | Dual-column (`user_id` FK still enforces for users); generic is for future; add app-level validation that all `participant_type=user` rows have valid `user_id` via `get_membership`. |
| Participant archived vs global confusion | user expects "archived for everyone" | Clarify in UI tooltip: "Archived only for you". Global status not in v1. |
| Search performance on ILIKE | scan on large table | Add `IX` on `title` + use `ILIKE` with `%q%` limited to 200 recent conversations per page; acceptable v1. |
| Message ordering under clock skew | bubbles out of order | Use DB `created_at` + `id` as secondary sort. |

---

## 16. Out of Scope (deferred via explicit TODOs)

- Adding/removing participants post-create (mentions `@user`).
- Leaving vs archiving, delete conversation.
- Message edit/delete, reactions, attachments.
- Pagination beyond 100 messages per thread (will add `cursor`).
- Real agent table + `agent: true` participation, agent-authored helper for renaming — plumbing only (the `rename` helper), not the agent runtime.
- Push/e-mail delivery for `is_registered==false` invites (already TODO at `workflows/__init__.py:192`).

---

## 17. Acceptance Criteria (done = all checked)

- [ ] New migration applies cleanly and rolls back.
- [ ] `POST /conversations` with workspace header creates thread + preview; rejects non-members and cross-workspace ids.
- [ ] `GET /conversations?archived=false` returns only current workspace & current user participations, excludes archived; `?archived=true` inverses; unread semantics as §7.2.
- [ ] `PATCH /conversations/{id}` renames; `ConversationService.rename` callable from agent context with same validation.
- [ ] `PATCH /conversations/{id}/read` clears `unread_count` without removing row; remains visible (just dot gone).
- [ ] `PATCH /conversations/{id}/archive` toggles per-user `archived_at` correctly.
- [ ] `GET /conversations?q=` searches title/participant/preview server-side.
- [ ] `POST /conversations/{id}/messages` appends, bumps preview, publishes durable event; other participants receive `Notification` row and `notification.created` WS; thread appends live via `message.created`.
- [ ] `GET /notifications` and `GET /conversations` both **require** `X-Workspace-ID`; missing returns 400; no cross-workspace leakage in any path.
- [ ] `GET /notifications/unread-count` and `GET /conversations/unread-count` both workspace-scoped and bell badge sums them.
- [ ] Session users bypass role check for both resources; API keys gated exactly as `require_key_permission`.
- [ ] Tiptap editor appears in compose + thread footer, persists markdown, renders as markdown bubbles; `npm run build` passes with no type errors.
- [ ] `InboxPage` tabs scale: Messages | Notifications with list+detail split, responsive like current `InboxPage.tsx:206` (`hidden md:flex`).
- [ ] `NotificationCenter` renders `conversation_message` specially and deep-links to `Messages` tab.
- [ ] `plans/inbox-messaging-plan.md` (this file) tracked in git on `feat/inbox-messaging`.

---

## 18. Next step

Approve this plan (or comment). On approval I will implement in story order S1→S9 on `feat/inbox-messaging`, running tests + `npm run build` after each story and requesting review before merge.
