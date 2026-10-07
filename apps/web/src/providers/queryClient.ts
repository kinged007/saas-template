import { QueryClient } from "@tanstack/react-query";

/**
 * True when the server answered with a 4xx. `statusCode` is stamped on every
 * error by `normalizeError` (dataProvider); 0 is its "no HTTP response"
 * sentinel, so anything other than 400-499 stays retryable.
 */
export function isClientError(error: unknown): boolean {
  const status = (error as { statusCode?: number } | null | undefined)?.statusCode;
  return typeof status === "number" && status >= 400 && status < 500;
}

/**
 * True when the server answered with a 5xx.
 */
export function isServerError(error: unknown): boolean {
  const status = (error as { statusCode?: number } | null | undefined)?.statusCode;
  return typeof status === "number" && status >= 500 && status < 600;
}

/**
 * True when no HTTP response arrived. `normalizeError` (dataProvider)
 * stamps `statusCode: 0` for an abort, a cancel and a dropped connection
 * alike. None of them can succeed on a retry of the same observer, so
 * retrying one only delays the failure the error branch exists to report.
 */
export function isNoResponseError(error: unknown): boolean {
  return (error as { statusCode?: number } | null | undefined)?.statusCode === 0;
}

/**
 * Singleton QueryClient for the app.
 *
 * Providing an explicit instance to <Refine> lets non-React code
 * (authProvider, axios interceptors) clear caches synchronously on
 * workspace / identity transitions. Without this, those modules would
 * need a React context to obtain the client.
 *
 * Refine's default `placeholderData: keepPreviousData` is intentionally
 * overridden to `undefined` – keptPreviousData makes list pages retain
 * the previous page's rows as placeholder while the next page fetches.
 * For workspace/user-scoped resources (inbox, members, api-keys, etc.)
 * that behaviour is exactly the "flash of old data" bug: after a
 * workspace switch or a logout→login as a different user, the stale
 * rows are kept as placeholder until the new workspace/user fetch
 * resolves. Disabling it forces a loading/empty state instead of stale.
 *
 * `retry` is react-query's own default budget (3 retries — 4 requests —
 * 1s + 2s + 4s) unless it is set here. Retrying a 4xx cannot succeed and
 * spent ~7s of "Loading…" in front of every refusal, so 4xx now fails on
 * the first attempt. A request that produced no HTTP response fails on the
 * first attempt too — it cannot succeed on a retry of the same observer.
 * Since then 5xx joins them and fails on the first attempt as well: four
 * identical requests against a 5xx-ing server cost ~7s of "Loading…", the
 * retry did not heal it anyway (same server, same request), and every error
 * state now surfaces a visible failure the user can re-run by hand (e.g. the
 * audit log's Try again).
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      placeholderData: undefined,
      retry: (failureCount, error) =>
        failureCount < 3 && !isClientError(error) && !isNoResponseError(error) && !isServerError(error),
    },
  },
});

/**
 * Hard-reset all workspace/user-scoped caches.
 * Must be called while the data subtree is unmounted (see WorkspaceContext
 * `switching` gate) so `removeQueries` truly drops the cache – a query
 * with active observers is retained until observers unmount.
 */
export function clearWorkspaceCaches(client: QueryClient = queryClient) {
  // Abort in-flight workspace-scoped requests so a late response from
  // the previous workspace can't repopulate the cache after it's cleared.
  client.cancelQueries({ queryKey: ["data"] });
  // `["data"]` is the root for every simple-rest resource (`["data","default",...]`).
  client.removeQueries({ queryKey: ["data"] });
  // `useCustom` (e.g. jobs/global) also lives under `["data"]`, so already covered.
  // `useCan` results depend on the active workspace's role.
  client.cancelQueries({ queryKey: ["access"] });
  client.removeQueries({ queryKey: ["access"] });
}

/**
 * Full reset – used on logout or user change. Drops identity/permissions
 * as well so the next login cannot flash the previous user's workspaces.
 */
export function clearAllCaches(client: QueryClient = queryClient) {
  client.cancelQueries();
  client.clear();
}
