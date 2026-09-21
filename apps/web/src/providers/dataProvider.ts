import type { DataProvider } from "@refinedev/core";
import axios, { type AxiosError, type AxiosRequestConfig } from "axios";
import dataProviderModule from "@refinedev/simple-rest";

import { tokenStore, workspaceStore } from "../utils/storage";
import { clearAllCaches, queryClient } from "./queryClient";

// Same-origin API path: the vite dev proxy (and nginx in production) forwards
// /api → backend, so no CORS/absolute-URL issues regardless of how the app is
// reached. Override with VITE_API_URL when a direct endpoint is preferred.
export const API_URL = import.meta.env.VITE_API_URL || "/api/v1";

export const httpClient = axios.create();

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
  const workspaceId = workspaceStore.get();
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

async function tryRefresh(): Promise<boolean> {
  if (!refreshPromise) {
    const capturedRefresh = tokenStore.getRefresh();
    if (!capturedRefresh) return false;
    refreshPromise = (async () => {
      try {
        const { data } = await axios.post(`${API_URL}/auth/refresh`, {
          refresh_token: capturedRefresh,
        });
        // Logout may have cleared tokens while refresh was in-flight —
        // don't restore a session the user just ended.
        if (tokenStore.getRefresh() !== capturedRefresh) return false;
        tokenStore.setTokens(data.access_token, data.refresh_token);
        return true;
      } catch {
        return false;
      } finally {
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

// FastAPI errors carry the human-readable reason in the `detail` body field.
// Surfaces it as the axios error message so refine notifications (and any
// direct callers) show *why* a request failed instead of just the status code.
function enrichErrorMessage(error: AxiosError): AxiosError {
  const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
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

httpClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    enrichErrorMessage(error);
    const original = error.config as RetriableRequest | undefined;
    if (error.response?.status === 401 && original && !original._retried) {
      original._retried = true;
      if (await tryRefresh()) {
        const access = tokenStore.getAccess();
        original.headers = { ...original.headers, Authorization: `Bearer ${access}` };
        return httpClient(original);
      }
    }
    if (error.response?.status === 401) {
      tokenStore.clear();
      clearAllCaches(queryClient);
      if (window.location.pathname !== "/login") {
        window.location.assign("/login");
      }
    }
    return Promise.reject(error);
  },
);

const baseDataProvider = dataProviderModule(API_URL, httpClient);

// `admin-users` / `admin-workspaces` are virtual resources: the list views
// read from the superuser-only GET /admin/* endpoints, which speak the same
// offset/limit + X-Total-Count dialect as every other list endpoint.
// They are not real REST resources (detail/toggle use `custom`), so only
// getList is overridden.
function adminList(path: string): DataProvider["getList"] {
  return async ({ pagination, filters, sorters }) => {
    const { currentPage = 1, pageSize = 10 } = pagination ?? {};
    const params = new URLSearchParams({
      offset: String((currentPage - 1) * pageSize),
      limit: String(pageSize),
    });
    for (const f of filters ?? []) {
      if (!("field" in f)) continue;
      // `q` is the cross-field search term (backend `?q=`), not a column.
      params.append(f.field === "q" ? "q" : `${f.field}_like`, String(f.value));
    }
    for (const s of sorters ?? []) {
      if (!s.field) continue;
      params.append("sort[]", s.field);
      params.append("order[]", s.order);
    }
    const { data, headers } = await httpClient.get(`${API_URL}${path}?${params}`);
    const total = Number(headers["x-total-count"]);
    return { data, total: Number.isFinite(total) ? total : data.length };
  };
}

const adminLists = {
  "admin-users": adminList("/admin/users"),
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
  getList: async (params) => {
    const admin = (adminLists as Record<string, DataProvider["getList"]>)[params.resource];
    if (admin) return admin(params);
    return baseDataProvider.getList(params);
  },
  custom: async ({ url, ...params }) => {
    const resolved =
      !url || /^https?:\/\//.test(url) || url.startsWith("/")
        ? url
        : `${API_URL}/${url}`;
    return baseDataProvider.custom({ url: resolved, ...params });
  },
};
