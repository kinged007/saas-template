import type { LiveProvider } from "@refinedev/core";

import { tokenStore } from "../utils/storage";

// Same-origin WebSocket: in dev the vite proxy forwards /api/v1/ws to the
// backend (works through outer proxies and locally); in production nginx does
// the same. Override with VITE_WS_URL when a direct endpoint is preferred.
const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
const WS_URL =
  import.meta.env.VITE_WS_URL || `${wsProtocol}://${window.location.host}/api/v1/ws`;

type Callback = (params: { type: string; payload: { ids?: string[]; data?: unknown } }) => void;

const callbacks = new Map<string, Set<Callback>>();
let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function connect() {
  const access = tokenStore.getAccess();
  if (!access) return;
  ws = new WebSocket(`${WS_URL}?token=${access}`);
  ws.onopen = () => console.info("[live] websocket connected");
  ws.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.event === "notification.created") {
        const id = message.data?.id;
        const listeners = callbacks.get("resources/notifications");
        listeners?.forEach((cb) =>
          cb({ type: "created", payload: { ids: id ? [id] : [], data: message.data } }),
        );
      } else if (message.event === "message.created") {
        const cid = message.data?.conversation_id as string | undefined;
        const mid = message.data?.message_id as string | undefined;
        // Invalidate conversation list (preview/unread) and the specific message stream.
        const convListeners = callbacks.get("resources/conversations");
        convListeners?.forEach((cb) =>
          cb({ type: "updated", payload: { ids: cid ? [cid] : [], data: message.data } }),
        );
        if (cid) {
          const msgChannel = `resources/conversations/${cid}/messages`;
          const msgListeners = callbacks.get(msgChannel);
          msgListeners?.forEach((cb) =>
            cb({ type: "created", payload: { ids: mid ? [mid] : [], data: message.data } }),
          );
          // Also generic messages channel
          const generic = callbacks.get("resources/messages");
          generic?.forEach((cb) =>
            cb({ type: "created", payload: { ids: mid ? [mid] : [], data: message.data } }),
          );
        }
      } else if (message.event === "conversation.renamed") {
        const cid = message.data?.conversation_id as string | undefined;
        const convListeners = callbacks.get("resources/conversations");
        convListeners?.forEach((cb) =>
          cb({ type: "updated", payload: { ids: cid ? [cid] : [], data: message.data } }),
        );
      }
    } catch {
      /* ignore malformed frames */
    }
  };
  ws.onclose = () => {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, 3000);
  };
  ws.onerror = () => ws?.close();
}

export const liveProvider: LiveProvider = {
  subscribe: ({ channel, callback }) => {
    if (!callbacks.has(channel)) callbacks.set(channel, new Set());
    callbacks.get(channel)!.add(callback as Callback);
    if (!ws || ws.readyState !== WebSocket.OPEN) connect();
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
