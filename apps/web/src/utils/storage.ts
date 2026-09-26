import { STORAGE_PREFIX } from "@/config";

const IDENTITY_KEY = `${STORAGE_PREFIX}_identity`;
// Per-user selection: the last workspace each user had open is restored on
// their next login. The shared key is the pre-upgrade fallback, adopted once.
const WORKSPACE_PREFIX = `${STORAGE_PREFIX}_workspace_id:`;
const LEGACY_WORKSPACE_KEY = `${STORAGE_PREFIX}_workspace_id`;

/**
 * Storage wrapper resilient to blocked/partitioned storage (e.g. sandboxed
 * iframes where `localStorage` access throws). Falls back to in-memory
 * storage so the app still renders; persistence is best-effort.
 */
function createSafeStorage() {
  const memory = new Map<string, string>();

  function getStore(): Storage | null {
    try {
      return window.localStorage;
    } catch {
      return null;
    }
  }

  return {
    get(key: string): string | null {
      const store = getStore();
      if (store) {
        try {
          return store.getItem(key);
        } catch {
          /* fall through to memory */
        }
      }
      return memory.has(key) ? (memory.get(key) as string) : null;
    },
    set(key: string, value: string): void {
      memory.set(key, value);
      const store = getStore();
      if (store) {
        try {
          store.setItem(key, value);
        } catch {
          /* memory copy already written */
        }
      }
    },
    remove(key: string): void {
      memory.delete(key);
      const store = getStore();
      if (store) {
        try {
          store.removeItem(key);
        } catch {
          /* ignore */
        }
      }
    },
  };
}

const storage = createSafeStorage();

type TokensListener = () => void;
const tokensListeners = new Set<TokensListener>();

// Access token lives in module memory only: the refresh token is an HttpOnly
// cookie (JS can never read it) and nothing persistent may hold either token.
let accessToken: string | null = null;

// Signed-in marker: set whenever a session is established (login, register,
// refresh, OAuth exchange, 2FA login) and cleared on logout. Lets the silent
// refresh short-circuit for visitors who never signed in, so logged-out
// boots never POST /auth/refresh just to learn they are logged out. A stale
// "1" (e.g. cookie cleared server-side) only costs one failed refresh.
const SESSION_KEY = `${STORAGE_PREFIX}_has_session`;

export const sessionHint = {
  get: () => storage.get(SESSION_KEY) === "1",
  set: () => storage.set(SESSION_KEY, "1"),
  clear: () => storage.remove(SESSION_KEY),
};

export const tokenStore = {
  getAccess: () => accessToken,
  setTokens: (access: string) => {
    accessToken = access;
    sessionHint.set();
    tokensListeners.forEach((listener) => listener());
  },
  clear: () => {
    accessToken = null;
    storage.remove(IDENTITY_KEY);
    sessionHint.clear();
    // Only the legacy shared workspace key is safe to drop blindly: the
    // per-user entry belongs to whoever logs in next and is restored then.
    storage.remove(WORKSPACE_PREFIX + "legacy");
    storage.remove(LEGACY_WORKSPACE_KEY);
    tokensListeners.forEach((listener) => listener());
  },
  /** Logout variant: also drops the signing-out user's workspace selection. */
  clearForUser: (userId?: string | null) => {
    accessToken = null;
    storage.remove(IDENTITY_KEY);
    sessionHint.clear();
    workspaceStore.clear(userId);
    tokensListeners.forEach((listener) => listener());
  },
  /**
   * Subscribe to token changes (login, refresh, logout). Returns an
   * unsubscribe function. Used by the realtime socket to reconnect with a
   * fresh token instead of retrying with a stale one.
   */
  onTokensChanged: (listener: TokensListener) => {
    tokensListeners.add(listener);
    return () => tokensListeners.delete(listener);
  },
};

export const identityStore = {
  get: () => {
    const raw = storage.get(IDENTITY_KEY);
    return raw ? JSON.parse(raw) : null;
  },
  set: (identity: unknown) => storage.set(IDENTITY_KEY, JSON.stringify(identity)),
};

/**
 * The single source of truth for the active workspace id.
 *
 * `stored` persists the selection per user. `active` mirrors it in memory
 * so the header, the context, and permission checks resolve identically
 * without re-deriving from different stores at different times.
 */
let active: string | null = null;

export function getActiveWorkspaceId(): string | null {
  return active;
}

export function setActiveWorkspaceId(id: string | null): void {
  active = id;
}

export const workspaceStore = {
  get: (userId?: string | null) => {
    if (userId) {
      const own = storage.get(WORKSPACE_PREFIX + userId);
      if (own) return own;
    }
    const legacy =
      storage.get(WORKSPACE_PREFIX + "legacy") ?? storage.get(LEGACY_WORKSPACE_KEY);
    if (legacy && userId) {
      // Adopt the pre-upgrade selection for this user, then drop the
      // shared key so it can never leak across users.
      storage.set(WORKSPACE_PREFIX + userId, legacy);
      storage.remove(LEGACY_WORKSPACE_KEY);
    }
    return legacy;
  },
  set: (id: string, userId?: string | null) =>
    storage.set(WORKSPACE_PREFIX + (userId ?? "legacy"), id),
  clear: (userId?: string | null) => {
    if (userId) storage.remove(WORKSPACE_PREFIX + userId);
    storage.remove(WORKSPACE_PREFIX + "legacy");
    storage.remove(LEGACY_WORKSPACE_KEY);
  },
};

const ONBOARDING_PREFIX = `${STORAGE_PREFIX}_onboarding_dismissed:`;

export const onboardingStore = {
  isDismissed: (workspaceId: string, userId?: string | null) =>
    storage.get(ONBOARDING_PREFIX + (userId ?? "legacy") + ":" + workspaceId) === "1",
  dismiss: (workspaceId: string, userId?: string | null) =>
    storage.set(ONBOARDING_PREFIX + (userId ?? "legacy") + ":" + workspaceId, "1"),
};
