import type { AuthProvider } from "@refinedev/core";

import { activeWorkspacePermissions } from "../utils/permissions";
import { API_URL, cancelPendingRefresh, httpClient } from "./dataProvider";
import {
  identityStore,
  tokenStore,
  workspaceStore,
  setActiveWorkspaceId,
} from "../utils/storage";
import { clearAllCaches, queryClient } from "./queryClient";
import type { Identity } from "../types";

const post = async (path: string, body: unknown) => {
  const resp = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const detail = (await resp.json().catch(() => null))?.detail;
    throw new Error(detail || `request failed (${resp.status})`);
  }
  return resp.status === 204 ? null : resp.json();
};

/**
 * Seed the persisted store + live header id BEFORE refine navigates: the
 * context auto-select only runs after the identity query settles, but list
 * queries fire on the same mount. Stored per-user selection wins; otherwise
 * the backend's first workspace (Acme Corp in this deployment). Failures
 * are non-fatal — the context falls back the same way.
 */
async function seedWorkspace(identity: Identity): Promise<void> {
  identityStore.set(identity);
  const stored = workspaceStore.get(identity.id);
  const next =
    identity.workspaces.find((w) => w.id === stored) ?? identity.workspaces[0];
  if (next) {
    workspaceStore.set(next.id);
    workspaceStore.set(next.id, identity.id);
    setActiveWorkspaceId(next.id);
  }
}

export const authProvider: AuthProvider = {
  login: async ({ email, password }) => {
    try {
      const tokens = await post("/auth/login", { email, password });
      // Drop the previous session's caches, workspace selection, and cached
      // identity before storing the new tokens: refine navigates to "/"
      // immediately and only invalidates the identity query ~32ms later, so
      // without this the app would mount with the previous user's workspace
      // id and rows (dashboard empty / notifications from the old workspace).
      // Unconditional — a no-op when logout already cleared.
      workspaceStore.clear();
      setActiveWorkspaceId(null);
      identityStore.set(null);
      clearAllCaches(queryClient);
      tokenStore.setTokens(tokens.access_token, tokens.refresh_token);
      try {
        const { data: identity } = await httpClient.get<Identity>(`${API_URL}/auth/me`);
        await seedWorkspace(identity);
      } catch {
        identityStore.set(null);
      }
      return { success: true, redirectTo: "/" };
    } catch (error) {
      return { success: false, error: error as Error };
    }
  },

  register: async ({ email, password, display_name, first_name, last_name }) => {
    try {
      // Prefer first/last; fall back to deprecated display_name for compat
      const body: Record<string, unknown> = { email, password };
      if (first_name || last_name) {
        body.first_name = first_name;
        body.last_name = last_name;
      } else if (display_name) {
        body.display_name = display_name;
      } else {
        // Keep for type compat — backend will 422
        body.display_name = display_name;
      }
      // Always forward first/last if present alongside display_name for transition
      if (first_name) body.first_name = first_name;
      if (last_name) body.last_name = last_name;
      if (display_name && !body.display_name) body.display_name = display_name;
      const tokens = await post("/auth/register", body);
      // Same stale-session reset + workspace seed as login (see above).
      workspaceStore.clear();
      setActiveWorkspaceId(null);
      identityStore.set(null);
      clearAllCaches(queryClient);
      tokenStore.setTokens(tokens.access_token, tokens.refresh_token);
      try {
        const { data: identity } = await httpClient.get<Identity>(`${API_URL}/auth/me`);
        await seedWorkspace(identity);
      } catch {
        identityStore.set(null);
      }
      return { success: true, redirectTo: "/" };
    } catch (error) {
      return { success: false, error: error as Error };
    }
  },

  logout: async () => {
    const refresh = tokenStore.getRefresh();
    if (refresh) {
      post("/auth/logout", { refresh_token: refresh }).catch(() => null);
    }
    cancelPendingRefresh();
    // Read the user id BEFORE clearing: the selection is keyed per user, so
    // logout drops only the signing-out user's entry.
    const cached = identityStore.get() as Identity | null;
    tokenStore.clearForUser(cached?.id);
    setActiveWorkspaceId(null);
    // Hard-reset before the router navigates to /login: every list/detail
    // query is workspace/user-scoped, so retaining it would flash the
    // previous user's rows when a different user logs in without a reload.
    clearAllCaches(queryClient);
    return { success: true, redirectTo: "/login" };
  },

  check: async () => {
    const access = tokenStore.getAccess();
    if (!access) return { authenticated: false, redirectTo: "/login" };
    return { authenticated: true };
  },

  onError: async (error) => {
    if ((error as { statusCode?: number })?.statusCode === 401) {
      tokenStore.clear();
      setActiveWorkspaceId(null);
      clearAllCaches(queryClient);
      return { logout: true, redirectTo: "/login" };
    }
    return { error };
  },

  getIdentity: async (): Promise<Identity | null> => {
    // Signed out (e.g. on /login): settle with null instead of firing
    // requests that 401 — the login flow invalidates and refetches identity.
    if (!tokenStore.getAccess()) return null;
    // httpClient (axios) instead of raw fetch: a transient 401 self-heals via
    // the refresh interceptor. Deliberately throw on failure instead of
    // returning null — returning null would settle the useGetIdentity query
    // "successfully" with no identity, so no retry would ever happen and
    // pages would mount before the workspace context exists.
    const { data: identity } = await httpClient.get<Identity>(`${API_URL}/auth/me`);
    identityStore.set(identity);
    return identity;
  },

  getPermissions: async (): Promise<string[]> => {
    const cached = identityStore.get() as Identity | null;
    return activeWorkspacePermissions(cached);
  },
};
