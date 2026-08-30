import type { LiveProvider } from "@refinedev/core";

import { tokenStore } from "../utils/storage";
import { applyMessageCreated, applyNotificationCreated } from "./liveCache";

// Same-origin WebSocket: in dev the vite proxy forwards /api/v1/ws to the
// backend (works through outer proxies and locally); in production nginx does
// the same. Override with VITE_WS_URL when a direct endpoint is preferred.
const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
const WS_URL =
  import.meta.env.VITE_WS_URL || `${wsProtocol}://${window.location.host}/api/v1/ws`;

// Heartbeat keeps intermediaries (nginx default: 60s idle) from dropping the
// connection; intervals stay well below that in both directions (client ping,
// server pong).
const PING_INTERVAL_MS = 25_000;
// Backoff schedule for reconnects with jitter, so a deployment blip doesn't
// turn every client into a synchronized reconnect storm.
const RECONNECT_DELAYS_MS = [1_000, 2_000, 5_000, 10_000];

export type LiveEventHandler = (event: { type: string; ids: string[]; data?: unknown }) => void;

/** Channel names the inbox components subscribe to. */
export const liveChannels = {
  notifications: "resources/notifications",
  conversations: "resources/conversations",
  conversationMessages: (conversationId: string) =>
    `resources/conversations/${conversationId}/messages`,
} as const;

type Callback = (params: { type: string; payload: { ids?: string[]; data?: unknown } }) => void;

const callbacks = new Map<string, Set<Callback>>();
let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let pingTimer: ReturnType<typeof setInterval> | null = null;
let reconnectAttempt = 0;

function stopPing(): void {
  if (pingTimer) clearInterval(pingTimer);
  pingTimer = null;
}

function send(frame: Record<string, unknown>): void {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(frame));
}

function scheduleReconnect(): void {
  if (reconnectTimer) return;
  const base = RECONNECT_DELAYS_MS[Math.min(reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)];
  const delay = base + Math.random() * base;
  reconnectAttempt += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

function closeSocket(): void {
  stopPing();
  if (!ws) return;
  ws.onclose = null;
  ws.onerror = null;
  ws.onmessage = null;
  ws.close();
  ws = null;
}

function connect(): void {
  const access = tokenStore.getAccess();
  if (!access) return;
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    reconnectAttempt = 0;
    console.info("[live] websocket connected");
    // First-message auth: the token never travels in the URL (proxy/access
    // logs). The server replies `{"event": "connected"}` once registered.
    send({ type: "auth", token: access });
    stopPing();
    pingTimer = setInterval(() => send({ type: "ping" }), PING_INTERVAL_MS);
  };

  ws.onmessage = (event) => {
    let message: { event?: string; data?: unknown };
    try {
      message = JSON.parse(event.data as string);
    } catch {
      return;
    }
    if (!message?.event || message.event === "pong" || message.event === "connected") return;
    dispatch(message.event, message.data);
  };

  ws.onclose = (event) => {
    stopPing();
    console.warn(`[live] websocket closed (code=${event.code}) — reconnecting`);
    scheduleReconnect();
  };
  ws.onerror = () => ws?.close();
}

function emit(channel: string, type: string, data: unknown): void {
  const listeners = callbacks.get(channel);
  listeners?.forEach((callback) => callback({ type, payload: { data } }));
}

function dispatch(event: string, data: unknown): void {
  if (event === "notification.created") {
    applyNotificationCreated(data);
    emit(liveChannels.notifications, "created", data);
  } else if (event === "agents.run.event") {
    // transient agent token/stream events — fanout, no cache patch needed (thread live will arrive as message.created)
    emit("resources/agents/run", "event", data);
    const cid = (data as { conversation_id?: string } | undefined)?.conversation_id;
    if (cid) emit(`resources/conversations/${cid}/run`, "event", data);
  } else if (event === "message.created") {
    applyMessageCreated(data);
    const conversationId = (data as { conversation_id?: string } | undefined)?.conversation_id;
    emit(liveChannels.conversations, "updated", data);
    if (conversationId) {
      emit(liveChannels.conversationMessages(conversationId), "created", data);
      emit("resources/messages", "created", data);
    }
  } else if (event === "conversation.renamed") {
    emit(liveChannels.conversations, "updated", data);
  }
}

// Reconnect with the fresh token on login/refresh; drop the socket on logout.
tokenStore.onTokensChanged(() => {
  closeSocket();
  if (tokenStore.getAccess()) connect();
});

/**
 * Typed subscription for app code: registers a handler and (re)opens the
 * socket if needed. Returns the unsubscribe function, so effects can simply
 * `return subscribeLive(...)`.
 */
export function subscribeLive(channel: string, handler: LiveEventHandler): () => void {
  if (!callbacks.has(channel)) callbacks.set(channel, new Set());
  callbacks.get(channel)!.add(handler as unknown as Callback);
  connect();
  return () => {
    callbacks.get(channel)?.delete(handler as unknown as Callback);
  };
}

export const liveProvider: LiveProvider = {
  subscribe: ({ channel, callback }) => {
    if (!callbacks.has(channel)) callbacks.set(channel, new Set());
    callbacks.get(channel)!.add(callback as Callback);
    connect();
    return Promise.resolve();
  },

  unsubscribe: ({ channel, callback }) => {
    callbacks.get(channel)?.delete(callback as Callback);
    return Promise.resolve();
  },

  publish: async () => {
    return;
  },
};
