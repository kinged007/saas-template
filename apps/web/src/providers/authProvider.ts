import type { AuthProvider } from "@refinedev/core";

import { activeWorkspacePermissions } from "../utils/permissions";
import { API_URL, httpClient } from "./dataProvider";
import { identityStore, tokenStore } from "../utils/storage";
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
      tokenStore.setTokens(tokens.access_token, tokens.refresh_token);
      return { success: true, redirectTo: "/" };
    } catch (error) {
      return { success: false, error: error as Error };
    }
  },

  register: async ({ email, password, display_name }) => {
    try {
      const tokens = await post("/auth/register", { email, password, display_name });
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
    tokenStore.clear();
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
