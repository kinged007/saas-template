import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useGetIdentity } from "@refinedev/core";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import type { Identity, Workspace } from "../types";
import { tokenStore, workspaceStore } from "../utils/storage";
import { clearAllCaches, clearWorkspaceCaches } from "../providers/queryClient";

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
  const { data: identity, isLoading, isError, refetch, error } = useGetIdentity<Identity & { workspaces: Workspace[] }>({
    queryOptions: IDENTITY_QUERY_OPTIONS,
  });
  const workspaces = identity?.workspaces ?? [];
  const identityId = (identity as Identity | null)?.id ?? null;

  const [selected, setSelected] = useState<Workspace | undefined>(() => {
    const id = workspaceStore.get();
    return workspaces.find((w) => w.id === id);
  });
  // "workspace" = only workspace-scoped caches (data + access) are dropped,
  // "all" = full reset including identity. `false` = no transition.
  const [switching, setSwitching] = useState<false | "workspace" | "all">(false);

  // Track previous ids to detect user / workspace changes that must
  // hard-reset caches before new data is painted (no stale flash).
  const prevIdentityIdRef = useRef<string | null>(null);
  const prevWorkspaceIdRef = useRef<string | null>(workspaceStore.get());
  // True after the first successful identity fetch – before that we must not
  // treat "no prev id → has id" as a user-change.
  const hasHydratedRef = useRef(false);

  // ---- Identity / user change: logout or login as different user ----------
  // useLayoutEffect → state update is flushed before browser paint, so the
  // stale subtree never reaches the screen.
  // Also handles the same-user stale case: when the token changed (logout +
  // login without an identity-id change), the authProvider cleared the
  // caches, but the stale `useGetIdentity` data may still be served first
  // (invalidate refetch resolves later). Clearing the selection up-front
  // forces the auto-selection effect below to re-pick from the FRESH
  // workspace list instead of keeping the previous session's id.
  useLayoutEffect(() => {
    if (isLoading || !hasHydratedRef.current) {
      if (identityId) hasHydratedRef.current = true;
      // Record the first identity id without triggering a reset.
      if (identityId && prevIdentityIdRef.current === null) {
        prevIdentityIdRef.current = identityId;
        prevWorkspaceIdRef.current = workspaceStore.get();
      }
      return;
    }
    // Fresh login over an unhydrated state (e.g. identity cleared on login
    // but the invalidation refetch has not resolved): drop any selection
    // restored from the previous session's stored workspace so the new
    // list picks its own default.
    // Skip when the restored selection already matches the fresh list —
    // e.g. a same-user re-login or a boot-time hydration where clearing
    // would only flash the "No workspace yet" empty state for a frame.
    if (prevIdentityIdRef.current === null && identityId !== null) {
      prevIdentityIdRef.current = identityId;
      if (selected) {
        const stored = workspaceStore.get();
        const restored = stored === selected.id && workspaces.some((w) => w.id === stored);
        if (!restored) {
          prevWorkspaceIdRef.current = stored;
          setSelected(undefined);
        }
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
      setSelected(undefined);
      setSwitching("all");
      return;
    }
    // User switched (logout+login in same tab without reload). prev and
    // current are both non-null but differ.
    if (prev !== null && identityId !== null && prev !== identityId) {
      prevIdentityIdRef.current = identityId;
      prevWorkspaceIdRef.current = workspaceStore.get();
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
  // If the resolved `next` differs from the currently selected workspace,
  // force the switching gate so caches are dropped while the subtree is
  // unmounted.
  useLayoutEffect(() => {
    if (workspaces.length === 0) {
      // Logged-out or identity not yet hydrated: don't auto-pick.
      if (!identityId) return;
      return;
    }
    const stored = workspaceStore.get();
    const found = workspaces.find((w) => w.id === stored);
    const next = found ?? workspaces[0];
    // No selected yet (first hydration): pick without switching – there is
    // no old workspace data to flash. The logout path already cleared caches.
    if (!selected) {
      workspaceStore.set(next.id);
      setSelected(next);
      prevWorkspaceIdRef.current = next.id;
      return;
    }
    if (next.id !== selected.id) {
      // Workspace must change but not via explicit setWorkspace – gate it.
      if (switching === false) {
        workspaceStore.set(next.id);
        // Keep selected as-is for one frame (children still mounted) – the
        // next render (switching=true) unmounts them before we wipe the
        // cache, which is required because removeQueries on queries with
        // active observers retains them until observers unmount.
        setSwitching("workspace");
        // selected update is deferred until after cache wipe (see switching
        // effect) to avoid a render where selected is new but cache is old.
        // Store the target so the post-wipe effect can apply it.
        prevWorkspaceIdRef.current = next.id;
      }
      return;
    }
    // Stable: keep store in sync and record. Also sync name/description/permission
    // changes (e.g. after PATCH /workspaces/:id) without triggering a cache wipe.
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
    workspaceStore.set(next.id);
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
      const targetId = prevWorkspaceIdRef.current ?? workspaceStore.get();
      const target = workspaces.find((w) => w.id === targetId) ?? workspaces[0];
      if (target) {
        workspaceStore.set(target.id);
        setSelected(target);
      }
    } else {
      clearWorkspaceCaches(queryClient);
      // Apply the pending workspace switch (stored in prev ref / store).
      const targetId = prevWorkspaceIdRef.current ?? workspaceStore.get();
      const target = workspaces.find((w) => w.id === targetId) ?? workspaces.find((w) => w.id === workspaceStore.get());
      if (target && target.id !== selected?.id) {
        setSelected(target);
      }
    }
    setSwitching(false);
  }, [switching, queryClient, workspaces, selected]);

  const value = useMemo<WorkspaceContextValue>(
    () => ({
      workspaces,
      workspace: selected,
      setWorkspace: (w) => {
        if (w.id === selected?.id) return;
        workspaceStore.set(w.id);
        prevWorkspaceIdRef.current = w.id;
        setSelected(w);
        setSwitching("workspace");
      },
      refresh: () => refetch(),
    }),
    [workspaces, selected, refetch],
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
    if (isLoading || !isError) {
      return null;
    }
    // Identity failed after retries: show a recovery screen instead of
    // silently mounting pages with no workspace (which 400s every
    // workspace-scoped call and empties the sidebar).
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-6">
        <p className="text-muted-foreground max-w-md text-center text-sm">
          Couldn't load your account
          {error ? `: ${String((error as { message?: string }).message ?? error)}` : ""}
        </p>
        <Button onClick={() => refetch()}>Try again</Button>
      </div>
    );
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
