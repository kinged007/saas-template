const IDENTITY_KEY = "tf_identity";
// Per-user selection: the last workspace each user had open is restored on
// their next login. The shared key is the pre-upgrade fallback, adopted once.
const WORKSPACE_PREFIX = "tf_workspace_id:";
const LEGACY_WORKSPACE_KEY = "tf_workspace_id";
const PENDING_INVITATION_KEY = "tf_pending_invitation";
const RETURN_TO_KEY = "tf_return_to";

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

// A throwing listener would skip every later listener and propagate out of
// setTokens, breaking the sign-in path that triggered it. So the error is
// swallowed, but never silently: dev logs the subscriber and its error
// (process.env.NODE_ENV is inlined by Vite, so this drops out of a build).
function notifyTokensChanged(): void {
  tokensListeners.forEach((listener) => {
    try {
      listener();
    } catch (e) {
      if (process.env.NODE_ENV !== "production") {
        console.error("[tokenStore] listener threw", listener, e);
      }
    }
  });
}

// Access token lives in module memory only: the refresh token is an HttpOnly
// cookie (JS can never read it) and nothing persistent may hold either token.
let accessToken: string | null = null;

// Signed-in marker: set whenever a session is established (login, register,
// refresh, OAuth exchange, 2FA login) and cleared on logout. Lets the silent
// refresh short-circuit for visitors who never signed in, so logged-out
// boots never POST /auth/refresh just to learn they are logged out. A stale
// "1" (e.g. cookie cleared server-side) only costs one failed refresh.
const SESSION_KEY = "tf_has_session";

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
    notifyTokensChanged();
  },
  clear: () => {
    accessToken = null;
    storage.remove(IDENTITY_KEY);
    sessionHint.clear();
    // Only the legacy shared workspace key is safe to drop blindly: the
    // per-user entry belongs to whoever logs in next and is restored then.
    storage.remove(WORKSPACE_PREFIX + "legacy");
    storage.remove(LEGACY_WORKSPACE_KEY);
    storage.remove(PENDING_INVITATION_KEY);
    // The session is over without an intentional redirect, so a destination
    // recorded by the guard belongs to whoever signs in next, not to them.
    storage.remove(RETURN_TO_KEY);
    notifyTokensChanged();
  },
  /** Logout variant: also drops the signing-out user's workspace selection. */
  clearForUser: (userId?: string | null) => {
    accessToken = null;
    storage.remove(IDENTITY_KEY);
    sessionHint.clear();
    storage.remove(PENDING_INVITATION_KEY);
    // An explicit logout returns nowhere, so a destination recorded by an
    // earlier guard redirect must not survive into the next sign-in.
    storage.remove(RETURN_TO_KEY);
    workspaceStore.clear(userId);
    notifyTokensChanged();
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

/**
 * Reset the outgoing session's selection state before new tokens land.
 * Called by `postCredentials()` on every sign-in path (login, register, 2FA,
 * OAuth code exchange): the in-memory active id is read synchronously by the
 * header and the dataProvider, so a stale one would scope the incoming user's
 * first requests to the previous workspace.
 * Per-user entries stay — the incoming user gets their own selection back.
 */
export function resetSessionState(): void {
  workspaceStore.clear();
  setActiveWorkspaceId(null);
  identityStore.set(null);
}

const ONBOARDING_PREFIX = "tf_onboarding_dismissed:";

const onboardingKey = (workspaceId: string, userId?: string | null) =>
  ONBOARDING_PREFIX + (userId ?? "legacy") + ":" + workspaceId;

export const onboardingStore = {
  isDismissed: (workspaceId: string, userId?: string | null) =>
    storage.get(onboardingKey(workspaceId, userId)) === "1",
  dismiss: (workspaceId: string, userId?: string | null) =>
    storage.set(onboardingKey(workspaceId, userId), "1"),
  /** Undo this user's own dismissal, bringing the card back. */
  clear: (workspaceId: string, userId?: string | null) =>
    storage.remove(onboardingKey(workspaceId, userId)),
};

/**
 * Invitation token from an emailed link, kept across the sign in / register
 * round trip so the auth provider can return the user to the accept page.
 */
export const pendingInvitationStore = {
  get: () => storage.get(PENDING_INVITATION_KEY),
  set: (token: string) => storage.set(PENDING_INVITATION_KEY, token),
  clear: () => storage.remove(PENDING_INVITATION_KEY),
};

/**
 * Where the auth guard denied a signed-out visitor, kept across the sign-in
 * round trip. Storage rather than router state because the SSO hop leaves the
 * page and comes back on a fresh URL.
 */
export const returnToStore = {
  set: (path: string) => storage.set(RETURN_TO_KEY, path),
  /** Read once and clear: the destination is spent the moment it is used. */
  take: () => {
    const path = storage.get(RETURN_TO_KEY);
    storage.remove(RETURN_TO_KEY);
    return path;
  },
  clear: () => storage.remove(RETURN_TO_KEY),
};
