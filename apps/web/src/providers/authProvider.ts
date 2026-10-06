import type { AuthProvider } from "@refinedev/core";

import { activeWorkspacePermissions } from "../utils/permissions";
import { API_URL, cancelPendingRefresh, ensureSession, httpClient } from "./dataProvider";
import {
  identityStore,
  pendingInvitationStore,
  returnToStore,
  tokenStore,
  workspaceStore,
  setActiveWorkspaceId,
} from "../utils/storage";
import { postCredentials } from "../utils/credentialPost";
import { clearAllCaches, queryClient } from "./queryClient";
import { sameOriginPath } from "../lib/sameOriginPath.ts";
import type { Identity } from "../types";

const post = async (path: string, body: unknown) => {
  const resp = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const detail = (await resp.json().catch(() => null))?.detail;
    // Preserve structured details (e.g. the 2FA challenge object) for callers
    // that branch on them; string details stay plain messages.
    throw new Error(
      typeof detail === "string" || detail == null
        ? detail || `request failed (${resp.status})`
        : JSON.stringify(detail),
    );
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
export async function seedWorkspace(identity: Identity): Promise<void> {
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

/**
 * Where a freshly authenticated user lands: the pending invitation accept
 * page when they arrived from an invite link, the destination the auth guard
 * recorded when it denied them, the dashboard otherwise.
 */
export const afterAuthRedirect = () => {
  // A pending invitation outranks the recorded destination: the invite is an
  // explicit, expiring, one-shot action, and skipping it would leave its token
  // stored to hijack the next sign-in.
  const token = pendingInvitationStore.get();
  if (token) {
    // The destination is not being honoured, so drop it — a later sign-in must
    // not land on a page this session never reached.
    returnToStore.clear();
    return `/invitations/accept?token=${encodeURIComponent(token)}`;
  }
  // take() consumes the destination, so one this guard rejects cannot be
  // replayed by a later sign-in either.
  const dest = returnToStore.take();
  return (dest && sameOriginPath(dest)) || "/";
};

export const authProvider: AuthProvider = {
  login: async ({ email, password }) => {
    try {
      const tokens = await postCredentials(() =>
        post("/auth/login", { email, password, use_cookies: true }),
      ).catch((err: unknown) => {
        // 2FA challenge: raw fetch stringifies an object detail — recover the
        // payload from the message when it parses as the challenge shape.
        const msg = (err as Error)?.message ?? "";
        let detail: unknown = null;
        try {
          detail = JSON.parse(msg);
        } catch {
          throw err;
        }
        if (
          typeof detail === "object" &&
          detail !== null &&
          (detail as { code?: string }).code === "2fa_required"
        ) {
          return { __challenge: (detail as { challenge_token: string }).challenge_token };
        }
        throw err;
      });
      if ("__challenge" in (tokens as object)) {
        return {
          success: false,
          error: new Error("2fa_required:" + (tokens as { __challenge: string }).__challenge),
        };
      }
      // The identity reset already ran, ahead of the POST (postCredentials).
      // Caches go now, before the new tokens land: refine navigates to "/"
      // immediately and only invalidates the identity query ~32ms later, so
      // without this the app would mount with the previous user's rows
      // (dashboard empty / notifications from the old workspace).
      // Unconditional — a no-op when logout already cleared.
      clearAllCaches(queryClient);
      tokenStore.setTokens(tokens.access_token);
      try {
        const { data: identity } = await httpClient.get<Identity>(`${API_URL}/auth/me`);
        await seedWorkspace(identity);
      } catch {
        identityStore.clear();
      }
      return { success: true, redirectTo: afterAuthRedirect() };
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
      const tokens = await postCredentials(() =>
        post("/auth/register", { ...body, use_cookies: true }),
      );
      // Same cache reset + workspace seed as login.
      clearAllCaches(queryClient);
      tokenStore.setTokens(tokens.access_token);
      try {
        const { data: identity } = await httpClient.get<Identity>(`${API_URL}/auth/me`);
        await seedWorkspace(identity);
      } catch {
        identityStore.clear();
      }
      return { success: true, redirectTo: afterAuthRedirect() };
    } catch (error) {
      return { success: false, error: error as Error };
    }
  },

  logout: async () => {
    if (tokenStore.getAccess()) {
      post("/auth/logout", {}).catch(() => null);
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
    // The access token is in-memory only, so a reload starts empty even with
    // a live cookie session. One silent refresh restores it; failure means
    // signed out. Shared single-flight with the dataProvider's 401 retries.
    if (tokenStore.getAccess()) return { authenticated: true };
    if (await ensureSession()) return { authenticated: true };
    return { authenticated: false, redirectTo: "/login" };
  },

  onError: async (error) => {
    if ((error as { statusCode?: number })?.statusCode === 401) {
      // tokenStore.clear() also drops the signed-in marker, so the next
      // check() short-circuits instead of retrying a dead session.
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
