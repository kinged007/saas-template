import { QueryClient } from "@tanstack/react-query";

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
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      placeholderData: undefined,
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
