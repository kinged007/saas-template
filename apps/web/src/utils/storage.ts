const ACCESS_KEY = "tf_access_token";
const REFRESH_KEY = "tf_refresh_token";
const IDENTITY_KEY = "tf_identity";
const WORKSPACE_KEY = "tf_workspace_id";

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

export const tokenStore = {
  getAccess: () => storage.get(ACCESS_KEY),
  getRefresh: () => storage.get(REFRESH_KEY),
  setTokens: (access: string, refresh: string) => {
    storage.set(ACCESS_KEY, access);
    storage.set(REFRESH_KEY, refresh);
  },
  clear: () => {
    storage.remove(ACCESS_KEY);
    storage.remove(REFRESH_KEY);
    storage.remove(IDENTITY_KEY);
    storage.remove(WORKSPACE_KEY);
  },
};

export const identityStore = {
  get: () => {
    const raw = storage.get(IDENTITY_KEY);
    return raw ? JSON.parse(raw) : null;
  },
  set: (identity: unknown) => storage.set(IDENTITY_KEY, JSON.stringify(identity)),
};

export const workspaceStore = {
  get: () => storage.get(WORKSPACE_KEY),
  set: (id: string) => storage.set(WORKSPACE_KEY, id),
};
