/**
 * Realtime cache patches: translate WebSocket frames into TanStack Query
 * cache updates so arriving messages and notifications render without any
 * refetch round-trips.
 *
 * Lives outside React on purpose — the socket dispatches frames from the
 * provider module, so patches use the shared `queryClient` singleton (same
 * pattern as the auth/axios cache resets).
 *
 * All patches are last-writer-wins on top of server truth: refine refetches
 * (on mount, on open, after mutations) reconcile any drift.
 */
import type { Query } from "@tanstack/react-query";

import type { Conversation, Message, Notification } from "../types";
import { getActiveWorkspaceId, identityStore } from "../utils/storage";
import { queryClient } from "./queryClient";

// Refine data query keys (verified against @refinedev/core key builders):
//   useList   → ["data", "<provider>", "<resource>", "list", params]
//   useCustom → ["data", "<provider>", "custom", params]   ← no resource segment
const DATA_ROOT = ["data", "default"] as const;
const CUSTOM_ROOT = ["data", "default", "custom"] as const;

function currentUserId(): string | undefined {
  return identityStore.get()?.id;
}

/**
 * Frames carry `workspace_id` (server notification payloads always set it).
 * Frames for a non-active workspace are ignored: the bell, badge, and lists
 * render the active workspace only. Cross-workspace rows arrive via refetch
 * after switching, never via live prepend into the wrong list.
 */
function isActiveWorkspace(frame: unknown): boolean {
  const active = getActiveWorkspaceId();
  // No selection yet (boot): let it through; the scoped queries refetch
  // with the header once the context hydrates.
  if (!active) return true;
  const ws = (frame as { workspace_id?: unknown } | null)?.workspace_id;
  // Frames without an id (legacy / non-workspace events) stay visible.
  if (typeof ws !== "string") return true;
  return ws === active;
}

// ---------------------------------------------------------------- primitives

/** Patch every refine `useList` cache for a resource. */
function patchListData<T>(
  resource: string,
  update: (items: T[]) => T[],
): void {
  queryClient.setQueriesData<{ data?: T[] } & Record<string, unknown>>(
    { queryKey: [...DATA_ROOT, resource, "list"] },
    (previous) =>
      previous?.data ? { ...previous, data: update(previous.data as T[]) } : previous,
  );
}

/**
 * Patch refine `useCustom` caches whose url contains `urlPart`.
 *
 * simple-rest's `custom()` resolves to `{ data: <response body> }`, so the
 * cached value wraps the payload in a `data` property — patches must update
 * `previous.data`, not the wrapper itself.
 */
function patchCustomData<T>(
  urlPart: string,
  update: (previous: T) => T,
): void {
  queryClient.setQueriesData<{ data?: T }>(
    {
      queryKey: [...CUSTOM_ROOT],
      predicate: (query: Query) => JSON.stringify(query.queryKey).includes(urlPart),
    },
    (previous) =>
      previous && previous.data != null
        ? { ...previous, data: update(previous.data) }
        : previous,
  );
}

function findCachedConversation(conversationId: string): Conversation | undefined {
  const caches = queryClient.getQueriesData<
    { data?: Conversation[] } & Record<string, unknown>
  >({ queryKey: [...DATA_ROOT, "conversations", "list"] });
  for (const [, cache] of caches) {
    const found = cache?.data?.find((conversation) => conversation.id === conversationId);
    if (found) return found;
  }
  return undefined;
}

/** Append a message to the cached thread (no-op when the thread isn't cached). */
export function upsertThreadMessage(conversationId: string, message: Message): void {
  patchCustomData<Message[]>(
    `conversations/${conversationId}/messages`,
    (messages) =>
      messages.some((m) => m.id === message.id) ? messages : [...messages, message],
  );
}

export function removeThreadMessage(conversationId: string, messageId: string): void {
  patchCustomData<Message[]>(
    `conversations/${conversationId}/messages`,
    (messages) => messages.filter((m) => m.id !== messageId),
  );
}

/** Patch the conversation list entry (preview, timestamp, unread count). */
function patchConversationEntry(
  conversationId: string,
  update: (conversation: Conversation) => Conversation,
): void {
  patchListData<Conversation>("conversations", (items) => {
    const next = items.map((conversation) =>
      conversation.id === conversationId ? update(conversation) : conversation,
    );
    // Keep the default "most recent activity first" order without a refetch.
    return next.sort((a, b) =>
      (b.last_message_at ?? "").localeCompare(a.last_message_at ?? ""),
    );
  });
}

// ------------------------------------------------------------------ events

interface MessageFrame {
  conversation_id?: string;
  message_id?: string;
  sender_id?: string;
  sender_type?: string;
  sender_name?: string;
  sender_avatar_url?: string | null;
  sender_email?: string | null;
  body?: string;
  body_preview?: string;
  created_at?: string;
}

/** Normalizes a `message.created` frame into the API's `Message` shape. */
function messageFromFrame(frame: MessageFrame): Message | null {
  if (!frame.conversation_id || !frame.message_id) return null;
  return {
    id: frame.message_id,
    conversation_id: frame.conversation_id,
    sender_type: (frame.sender_type as Message["sender_type"]) ?? "user",
    sender_id: frame.sender_id ?? "",
    sender_name: frame.sender_name ?? frame.sender_id ?? "",
    sender_avatar_url: frame.sender_avatar_url ?? null,
    sender_email: frame.sender_email ?? null,
    body: frame.body ?? "",
    body_html: null,
    created_at: frame.created_at ?? new Date().toISOString(),
    updated_at: undefined,
  };
}

/**
 * A message arrived (WS push or own send): append it to the thread, bump the
 * conversation list entry and the unread counters — the bell badge ticks on
 * every incoming message from someone else, even while the thread is open.
 * Read-state is cleared by engaging with the conversation (opening it again
 * or sending), not silently while the user watches it arrive.
 */
export function applyMessageCreated(frame: unknown): void {
  if (!isActiveWorkspace(frame)) return;
  const data = (frame ?? {}) as MessageFrame;
  const message = messageFromFrame(data);
  if (!message) return;
  const conversationId = message.conversation_id;
  const isOwnMessage = data.sender_id !== undefined && data.sender_id === currentUserId();
  const countsAsUnread = !isOwnMessage;

  // Read the cached unread state BEFORE patching the list entry.
  const cachedUnread = findCachedConversation(conversationId)?.unread_count;

  upsertThreadMessage(conversationId, message);

  patchConversationEntry(conversationId, (conversation) => ({
    ...conversation,
    last_message_at: message.created_at,
    last_message_preview: data.body_preview ?? conversation.last_message_preview,
    unread_count: countsAsUnread ? conversation.unread_count + 1 : conversation.unread_count,
  }));

  if (!countsAsUnread) return;

  patchCustomData<{ count: number; unread_conversations: number }>(
    "conversations/unread-count",
    (previous) => ({
      count: previous.count + 1,
      // Only a new conversation is "newly unread"; if the cached list entry
      // already had unread > 0 (or is unknown) it was already counted.
      unread_conversations:
        previous.unread_conversations + (cachedUnread === 0 ? 1 : 0),
    }),
  );
}

/**
 * A notification arrived: prepend it to the unread list caches and bump the
 * bell badge. `conversation_message` pointers are excluded from the badge —
 * they are surfaced via conversation unread counts instead.
 */
export function applyNotificationCreated(frame: unknown): void {
  if (!isActiveWorkspace(frame)) return;
  const data = (frame ?? {}) as Partial<Notification> | null;
  if (!data?.id) return;
  const notification: Notification = {
    id: data.id,
    workspace_id: data.workspace_id ?? "",
    type: data.type ?? "",
    title: data.title ?? "",
    body: data.body,
    payload: data.payload,
    acknowledged: false,
    acknowledged_at: data.acknowledged_at,
    created_at: data.created_at ?? new Date().toISOString(),
  };

  patchListData<Notification>("notifications", (items) =>
    items.some((n) => n.id === notification.id) ? items : [notification, ...items],
  );

  if (notification.type === "conversation_message") return;
  patchCustomData<{ count: number }>("notifications/unread-count", (previous) => ({
    count: previous.count + 1,
  }));
}

/**
 * The user read a conversation: zero its unread badge locally and refresh the
 * aggregate counters (cheap SQL counts; they also account for the notification
 * pointers the backend acknowledges on read).
 */
export function applyConversationRead(conversationId: string): void {
  patchConversationEntry(conversationId, (conversation) => ({
    ...conversation,
    unread_count: 0,
  }));
  void queryClient.invalidateQueries({
    predicate: (query: Query) =>
      JSON.stringify(query.queryKey).includes("unread-count"),
  });
}

