import type { DataProvider } from "@refinedev/core";
import axios, { type AxiosError, type AxiosRequestConfig } from "axios";
import dataProviderModule from "@refinedev/simple-rest";

import { tokenStore, workspaceStore, identityStore, getActiveWorkspaceId, sessionHint } from "../utils/storage";
import { adminListQuery } from "./adminListQuery";
import { clearAllCaches, queryClient } from "./queryClient";
import { hasReadById, resourcePath } from "./resourcePaths";
import { withRefreshLock } from "./refreshLock";

// Same-origin API path: the vite dev proxy (and nginx in production) forwards
// /api → backend, so no CORS/absolute-URL issues regardless of how the app is
// reached. Override with VITE_API_URL when a direct endpoint is preferred.
export const API_URL = import.meta.env.VITE_API_URL || "/api/v1";

export const httpClient = axios.create({ withCredentials: true });

/** True when the JWT's `exp` claim has passed (with a small clock-skew buffer). */
function isAccessTokenExpired(token: string | null): boolean {
  if (!token) return false;
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return typeof payload.exp === "number" && payload.exp * 1000 <= Date.now() + 10_000;
  } catch {
    return false; // unparseable — let the server decide
  }
}

httpClient.interceptors.request.use(async (config) => {
  let access = tokenStore.getAccess();
  // Refresh BEFORE sending when the access token is already expired, so the
  // request goes out with a valid token instead of 401ing and recovering via
  // the response interceptor (which logs a 401 to the console on every boot
  // with a stale token).
  if (isAccessTokenExpired(access)) {
    if (await tryRefresh()) {
      access = tokenStore.getAccess();
    }
  }
  if (access) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${access}`;
  }
  // Single source of truth: the in-memory active id, synchronously
  // committed by login / switch / logout alongside the persisted store.
  // The store reads are boot fallbacks only (fresh page load before the
  // context hydrates) — never a re-derivation that can disagree.
  const cached = identityStore.get() as { id?: string } | null;
  const workspaceId =
    getActiveWorkspaceId() ?? workspaceStore.get(cached?.id) ?? workspaceStore.get();
  if (workspaceId) {
    config.headers = config.headers ?? {};
    config.headers["X-Workspace-ID"] = workspaceId;
  }
  return config;
});

type RetriableRequest = AxiosRequestConfig & { _retried?: boolean };

// The backend rotates refresh tokens (old one is revoked), so a single refresh
// must serve all concurrent 401 retries — otherwise the second refresh would
// fail with an already-revoked token and log the user out.
let refreshPromise: Promise<boolean> | null = null;

export function cancelPendingRefresh() {
  refreshPromise = null;
}

/**
 * Shared single-flight session restore: one refresh serves all concurrent
 * callers (boot check + a 401 retry racing would otherwise double-rotate a
 * rotating refresh token and log the user out). Returns false immediately
 * when the signed-in marker is absent, so logged-out boots never POST.
 */
export async function ensureSession(): Promise<boolean> {
  if (!sessionHint.get()) return false;
  return tryRefresh();
}

async function tryRefresh(): Promise<boolean> {
  if (!refreshPromise) {
    // The refresh token travels in the HttpOnly cookie (withCredentials) —
    // JS never sees it.
    const capturedAccess = tokenStore.getAccess();
    refreshPromise = withRefreshLock(async () => {
      try {
        const { data } = await axios.post(
          `${API_URL}/auth/refresh`,
          {},
          {
            withCredentials: true,
            headers: { "X-Requested-With": "XMLHttpRequest" },
            // The Web Lock is exclusive for this call's whole duration, and every
            // request awaits tryRefresh() while the access token is expired, so a
            // stalled POST would block every tab of the origin indefinitely.
            timeout: 15_000,
          },
        );
        // Logout may have cleared tokens while refresh was in-flight —
        // don't restore a session the user just ended.
        if (capturedAccess !== null && tokenStore.getAccess() !== capturedAccess) return false;
        if (!data?.access_token) return false;
        tokenStore.setTokens(data.access_token);
        return true;
      } catch {
        return false;
      } finally {
        refreshPromise = null;
      }
    });
  }
  return refreshPromise;
}

// FastAPI errors carry the human-readable reason in the `detail` body field.
// Surfaces it as the axios error message so refine notifications (and any
// direct callers) show *why* a request failed instead of just the status code.
function normalizeError(error: AxiosError): AxiosError {
  // refine reads `statusCode` for its generic error notification and
  // authProvider.onError reads it to detect a 401; axios errors carry no such
  // field, so without this every notification says "status code: undefined".
  // 0 is the "no HTTP response" sentinel (offline, DNS, CORS, abort) — refine
  // always renders a status code, so the notification strips the parenthetical
  // for anything that is not a real HTTP status.
  Object.assign(error, { statusCode: error.response?.status ?? 0 });
  const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
  // 2FA challenge responses carry an object detail ({code: "2fa_required",
  // challenge_token}) — leave the message alone so the login page can branch
  // on the structured payload instead of showing "[object Object]".
  if (typeof detail === "object" && detail !== null && !Array.isArray(detail)) {
    return error;
  }
  if (typeof detail === "string" && detail) {
    error.message = detail;
  } else if (Array.isArray(detail) && detail.length > 0) {
    error.message = detail
      .map((entry) =>
        typeof entry === "object" && entry !== null && "msg" in entry
          ? String((entry as { msg: unknown }).msg)
          : String(entry),
      )
      .join("; ");
  }
  return error;
}

function forceLogout() {
  // Revoked/expired session: drop everything synchronously so no further
  // request can go out with the dead tokens, then bounce to /login. The
  // queryClient listener notifies the live socket via onTokensChanged.
  // tokenStore.clear() also drops the signed-in marker.
  const hadSession = Boolean(tokenStore.getAccess());
  tokenStore.clear();
  clearAllCaches(queryClient);
  if (hadSession && window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

httpClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    normalizeError(error);
    const original = error.config as RetriableRequest | undefined;
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (error.response?.status === 401 && original && !original._retried) {
      // The session row is gone — no refresh token can resurrect it.
      // Skip the doomed refresh round-trip and log out immediately.
      if (detail === "session revoked") {
        forceLogout();
        return Promise.reject(error);
      }
      original._retried = true;
      if (await tryRefresh()) {
        const access = tokenStore.getAccess();
        original.headers = { ...original.headers, Authorization: `Bearer ${access}` };
        return httpClient(original);
      }
    }
    if (error.response?.status === 401) {
      forceLogout();
    }
    return Promise.reject(error);
  },
);

const baseDataProvider = dataProviderModule(API_URL, httpClient);

// `admin-workspaces` / `admin-audit` are virtual resources: the list views
// read from the superuser-only GET /admin/* endpoints, which speak the same
// offset/limit + X-Total-Count dialect as every other list endpoint.
// They are not real REST resources (detail/toggle use `custom`), so only
// getList is overridden. (`admin-users` maps through `resourcePath()`.)
function adminList(path: string): DataProvider["getList"] {
  return async ({ pagination, filters, sorters }) => {
    const { currentPage = 1, pageSize = 10 } = pagination ?? {};
    const params = adminListQuery({ currentPage, pageSize, filters, sorters });
    const { data, headers } = await httpClient.get(`${API_URL}${path}?${params}`);
    const total = Number(headers["x-total-count"]);
    return { data, total: Number.isFinite(total) ? total : data.length };
  };
}

const adminLists = {
  "admin-workspaces": adminList("/admin/workspaces"),
  "admin-audit": adminList("/admin/audit"),
} as const;

/**
 * simple-rest's `custom` uses the url verbatim — it never prepends the API
 * base URL. Resolve relative custom urls against API_URL so useCustom /
 * useCustomMutation calls (e.g. `jobs/{id}/trigger`)
 * hit the backend instead of resolving against the current page.
 */
export const dataProvider: DataProvider = {
  ...baseDataProvider,
  getList: ({ resource, ...params }) => {
    const admin = (adminLists as Record<string, DataProvider["getList"]>)[resource];
    if (admin) return admin({ resource, ...params });
    return baseDataProvider.getList({ resource: resourcePath(resource), ...params });
  },
  getOne: async ({ resource, ...params }) => {
    if (!hasReadById(resource)) {
      // `statusCode` is what queryClient.isClientError reads, so a 4xx stops
      // react-query retrying a request that was never sent — the API would
      // answer 405/404 for it anyway.
      throw Object.assign(
        new Error(
          `getOne("${resource}") has no backend route: the API serves no GET /${resourcePath(resource)}/{id}. Fetch the collection with custom (GET /${resourcePath(resource)}) and filter instead.`,
        ),
        { statusCode: 405 },
      );
    }
    return baseDataProvider.getOne({ resource: resourcePath(resource), ...params });
  },
  getMany: ({ resource, ...params }) =>
    baseDataProvider.getMany({ resource: resourcePath(resource), ...params }),
  update: ({ resource, ...params }) =>
    baseDataProvider.update({ resource: resourcePath(resource), ...params }),
  create: ({ resource, ...params }) =>
    baseDataProvider.create({ resource: resourcePath(resource), ...params }),
  deleteOne: ({ resource, ...params }) =>
    baseDataProvider.deleteOne({ resource: resourcePath(resource), ...params }),
  custom: async ({ url, ...params }) => {
    const resolved =
      !url || /^https?:\/\//.test(url) || url.startsWith("/")
        ? url
        : `${API_URL}/${url}`;
    return baseDataProvider.custom({ url: resolved, ...params });
  },
};
