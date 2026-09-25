import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { Identity, Workspace } from "../types";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  tokenStore,
  workspaceStore,
  identityStore,
  getActiveWorkspaceId,
  setActiveWorkspaceId,
} from "../utils/storage";
import { clearAllCaches, clearWorkspaceCaches } from "../providers/queryClient";
import { API_URL, httpClient } from "../providers/dataProvider";

type WorkspaceContextValue = {
  workspaces: Workspace[];
  workspace?: Workspace;
  setWorkspace: (workspace: Workspace) => void;
  refresh: () => void;
};

const WorkspaceContext = createContext<WorkspaceContextValue>({
  workspaces: [],
  setWorkspace: () => undefined,
  refresh: () => undefined,
});

export const useWorkspace = () => useContext(WorkspaceContext);

// refine's useGetIdentity defaults to retry: false; a transient /me failure
// would otherwise settle with no identity and mount pages without a workspace.
// Shared by every useGetIdentity observer so they don't override each other's
// options on the shared query (react-query merges observer options).
export const IDENTITY_QUERY_OPTIONS = {
  staleTime: 30_000,
  retry: 2,
  retryDelay: (attempt: number) => Math.min(500 * 2 ** attempt, 4000),
};

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  // NOTE: no useGetIdentity observer here. This provider used to host its own
  // observer with shared IDENTITY_QUERY_OPTIONS, but react-query merges
  // observer options onto the SHARED identity query — and this provider
  // remounts on every login/logout navigation, which re-created its observer
  // mid-flight and wedged the query (isLoading stuck true, data never
  // delivered) even though /auth/me returned 200 with 2 workspaces.
  // Instead the identity is read from the react-query cache (written by the
  // long-lived useGetIdentity observers in AppLayout/pages) with the
  // login()-cached identityStore as the pre-hydration fallback. The
  // useSyncExternalStore subscription re-renders this provider whenever the
  // identity cache entry changes, so hydration propagates without an
  // observer of our own.
  const cachedIdentity = useSyncExternalStore(
    (onChange) => queryClient.getQueryCache().subscribe(onChange),
    () => queryClient.getQueryData<Identity & { workspaces: Workspace[] }>(["auth", "identity"]),
    () => undefined,
  );
  const storedIdentity = (identityStore.get() as (Identity & { workspaces: Workspace[] }) | null);
  const identity = cachedIdentity ?? storedIdentity ?? undefined;
  const isLoading = identity === undefined;
  const [identityError, setIdentityError] = useState<unknown>(null);
  const fetchingRef = useRef(false);

  // Self-healing identity fetch. Tokens valid + no cached/stored identity
  // (e.g. a login that stored tokens but never seeded identity) would
  // otherwise gate on `return null` forever: this provider's children —
  // the only useGetIdentity observers — stay unmounted, so nobody ever
  // fills the cache. A direct fetch (not another observer) avoids the
  // observer-remount wedging described below.
  const fetchIdentity = useCallback(async () => {
    if (fetchingRef.current) return;
    fetchingRef.current = true;
    setIdentityError(null);
    try {
      const { data } = await httpClient.get<Identity & { workspaces: Workspace[] }>(
        `${API_URL}/auth/me`,
      );
      identityStore.set(data);
      queryClient.setQueryData(["auth", "identity"], data);
    } catch (e) {
      // 401s are handled by the httpClient interceptor (refresh, else clear
      // tokens + redirect to /login) — only surface non-auth failures here.
      if (tokenStore.getAccess()) setIdentityError(e);
    } finally {
      fetchingRef.current = false;
    }
  }, [queryClient]);

  useEffect(() => {
    if (tokenStore.getAccess() && identity === undefined) {
      void fetchIdentity();
    }
  }, [identity, fetchIdentity]);

  const refetch = () => {
    queryClient.invalidateQueries({ queryKey: ["auth"] });
    void fetchIdentity();
  };
  const workspaces = identity?.workspaces ?? [];
  // identityId doubles as the workspaceStore key (per-user selection).
  // identityStore.get() is the post-login fallback: login() caches the
  // fresh identity there before the identity query settles.
  const identityId = (identity as Identity | null)?.id
    ?? (identityStore.get() as Identity | null)?.id
    ?? null;

  const [selected, setSelected] = useState<Workspace | undefined>(() => {
    const id = getActiveWorkspaceId() ?? workspaceStore.get(identityId);
    return workspaces.find((w) => w.id === id);
  });
  // "workspace" = only workspace-scoped caches (data + access) are dropped,
  // "all" = full reset including identity. `false` = no transition.
  const [switching, setSwitching] = useState<false | "workspace" | "all">(false);

  // Track previous ids to detect user / workspace changes that must
  // hard-reset caches before new data is painted (no stale flash).
  const prevIdentityIdRef = useRef<string | null>(null);
  const prevWorkspaceIdRef = useRef<string | null>(
    getActiveWorkspaceId() ?? workspaceStore.get(identityId),
  );
  // True after the first successful identity fetch – before that we must not
  // treat "no prev id → has id" as a user-change.
  const hasHydratedRef = useRef(false);

  // One commit path for every selection change: persisted store, live header
  // id, and React state move together, so the switcher label, the request
  // header, and permission checks can never disagree mid-transition.
  // `deferState` keeps the old selection painted for one frame while the
  // `switching` gate unmounts the subtree before the cache wipe.
  const commitSelection = (
    next: Workspace,
    userId: string | null,
    opts?: { deferState?: boolean },
  ) => {
    workspaceStore.set(next.id, userId);
    setActiveWorkspaceId(next.id);
    prevWorkspaceIdRef.current = next.id;
    if (!opts?.deferState) setSelected(next);
  };

  // ---- Identity / user change: logout or login as different user ----------
  // useLayoutEffect → state update is flushed before browser paint, so the
  // stale subtree never reaches the screen.
  useLayoutEffect(() => {
    if (isLoading || !hasHydratedRef.current) {
      if (identityId) hasHydratedRef.current = true;
      // Record the first identity id without triggering a reset.
      if (identityId && prevIdentityIdRef.current === null) {
        prevIdentityIdRef.current = identityId;
        prevWorkspaceIdRef.current =
          getActiveWorkspaceId() ?? workspaceStore.get(identityId);
      }
      return;
    }
    const prev = prevIdentityIdRef.current;
    // Logged out: identity went from set → null (token cleared). Full reset
    // so the next login cannot flash the previous user's rows. The singleton
    // clear in authProvider already did this synchronously; this is the
    // safety net for 401-interceptor and cross-tab storage events.
    if (prev !== null && identityId === null) {
      prevIdentityIdRef.current = null;
      prevWorkspaceIdRef.current = null;
      setActiveWorkspaceId(null);
      setSelected(undefined);
      setSwitching("all");
      return;
    }
    // User switched (logout+login in same tab without reload). prev and
    // current are both non-null but differ.
    if (prev !== null && identityId !== null && prev !== identityId) {
      prevIdentityIdRef.current = identityId;
      prevWorkspaceIdRef.current =
        getActiveWorkspaceId() ?? workspaceStore.get(identityId);
      setSwitching("all");
      return;
    }
    if (identityId) {
      prevIdentityIdRef.current = identityId;
      if (!hasHydratedRef.current) hasHydratedRef.current = true;
    }
  }, [identityId, isLoading]);

  // ---- Workspace auto-selection (initial load & removals) -------------------
  // This handles the case where the stored workspace id is not in the new
  // workspaces list (e.g. after login as different user where the logout
  // path didn't trigger, or the user was removed from the active workspace).
  // Resolution order: per-user stored → live/fallback id → first workspace
  // returned by the API.
  useLayoutEffect(() => {
    if (workspaces.length === 0) {
      // Logged-out or identity not yet hydrated: don't auto-pick.
      if (!identityId) return;
      return;
    }
    const stored = workspaceStore.get(identityId);
    const found = workspaces.find((w) => w.id === stored);
    const fallbackId = getActiveWorkspaceId() ?? workspaceStore.get();
    const next = found
      ?? workspaces.find((w) => w.id === fallbackId)
      ?? workspaces[0];
    // No selected yet (first hydration): pick without switching – there is
    // no old workspace data to flash. The logout path already cleared caches.
    if (!selected) {
      commitSelection(next, identityId);
      return;
    }
    if (next.id !== selected.id) {
      // Workspace must change but not via explicit setWorkspace – gate it:
      // commit the stores now (so any request fired mid-transition carries
      // the new id) but defer the painted selection until the gate has
      // unmounted the subtree and wiped the old workspace's cache.
      if (switching === false) {
        commitSelection(next, identityId, { deferState: true });
        setSwitching("workspace");
      }
      return;
    }
    // Stable: keep stores in sync and record. Also sync name/description/
    // permission changes (e.g. after PATCH /workspaces/:id) without a wipe.
    if (
      selected.name !== next.name ||
      selected.description !== next.description ||
      selected.slug !== next.slug ||
      // permissions/role may have changed after a role update
      JSON.stringify(selected.permissions) !== JSON.stringify(next.permissions) ||
      selected.role !== next.role
    ) {
      setSelected(next);
    }
    workspaceStore.set(next.id, identityId);
    setActiveWorkspaceId(next.id);
    prevWorkspaceIdRef.current = next.id;
  }, [workspaces, selected, identityId, switching]);

  // ---- Switching gate: wipe caches while subtree is unmounted --------------
  useEffect(() => {
    if (!switching) return;
    // Runs after the old subtree committed its unmount (children are not
    // mounted, so queries have no active observers). This truly drops them
    // from the cache; removeQueries on a query with active observers would
    // keep the observers serving the old data until the refetch resolves.
    if (switching === "all") {
      clearAllCaches(queryClient);
      // After a full reset the identity query itself was cleared – it will
      // refetch on the next mount. Resolve the target workspace from the
      // (already fetched) identity or fall back to store; the workspaces
      // layout effect will re-sync on the next hydration anyway.
      const targetId = prevWorkspaceIdRef.current ?? workspaceStore.get(identityId);
      const target = workspaces.find((w) => w.id === targetId) ?? workspaces[0];
      if (target) {
        workspaceStore.set(target.id, identityId);
        setActiveWorkspaceId(target.id);
        setSelected(target);
      }
    } else {
      clearWorkspaceCaches(queryClient);
      // Apply the pending switch deferred above (stored in prev ref / store).
      const targetId = prevWorkspaceIdRef.current ?? workspaceStore.get(identityId);
      const target = workspaces.find((w) => w.id === targetId)
        ?? workspaces.find((w) => w.id === workspaceStore.get(identityId));
      if (target && target.id !== selected?.id) {
        setSelected(target);
      }
    }
    setSwitching(false);
  }, [switching, queryClient, workspaces, selected, identityId]);

  const value = useMemo<WorkspaceContextValue>(
    () => ({
      workspaces,
      workspace: selected,
      setWorkspace: (w) => {
        if (w.id === selected?.id) return;
        commitSelection(w, identityId);
        setSwitching("workspace");
      },
      refresh: () => refetch(),
    }),
    // commitSelection is stable in practice (refs + setters only); identityId
    // is listed so the closure never captures a stale user key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [workspaces, selected, refetch, identityId],
  );

  // Signed out (e.g. on /login): render children and let the Authenticated
  // guard route to the login flow. Caches were already cleared synchronously
  // in authProvider.logout / the 401 interceptor.
  if (!tokenStore.getAccess()) {
    return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
  }

  // Identity still loading (initial fetch or retries): block workspace-scoped
  // pages so requests always carry X-Workspace-ID. Deliberately keyed on
  // isLoading / !identity — NOT isFetching — so background refetches (e.g.
  // the invalidation after login) never unmount the app. Unmounting on
  // isFetching would remount fresh useGetIdentity observers (staleTime 0),
  // which refetch, which re-triggers the gate: an endless flash loop.
  if (isLoading || !identity) {
    // Identity fetch failed after retries: show a recovery screen instead of
    // silently mounting pages with no workspace (which 400s every
    // workspace-scoped call and empties the sidebar).
    if (identityError) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-6">
          <p className="text-muted-foreground max-w-md text-center text-sm">
            Couldn't load your account
            {identityError
              ? `: ${String((identityError as { message?: string }).message ?? identityError)}`
              : ""}
          </p>
          <div className="flex gap-2">
            <Button onClick={() => refetch()}>Try again</Button>
            <Button variant="outline" asChild>
              {/* plain anchor: this tree may render outside the router */}
              <a href="/">Back to dashboard</a>
            </Button>
          </div>
        </div>
      );
    }
    return null;
  }

  // Transition gate: old data already unmounted, caches reset pending,
  // new workspace about to mount — hold the frame so the next paint can
  // never contain the previous workspace/user's rows.
  if (switching) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground text-sm">Loading workspace…</p>
      </div>
    );
  }

  // Workspace known but not yet selected: block until the effect picks one.
  if (workspaces.length > 0 && !selected) {
    return null;
  }

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
