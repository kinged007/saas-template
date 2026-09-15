import type { AuthProvider } from "@refinedev/core";

import { activeWorkspacePermissions } from "../utils/permissions";
import { API_URL, cancelPendingRefresh, httpClient } from "./dataProvider";
import { identityStore, tokenStore, workspaceStore } from "../utils/storage";
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
      identityStore.set(null);
      clearAllCaches(queryClient);
      tokenStore.setTokens(tokens.access_token, tokens.refresh_token);
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
      // Same stale-session reset as login (see above).
      workspaceStore.clear();
      identityStore.set(null);
      clearAllCaches(queryClient);
      tokenStore.setTokens(tokens.access_token, tokens.refresh_token);
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
    tokenStore.clear();
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
