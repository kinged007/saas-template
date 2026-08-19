import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useGetIdentity } from "@refinedev/core";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import type { Workspace } from "../types";
import { tokenStore, workspaceStore } from "../utils/storage";

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
  const { data: identity, isLoading, isError, refetch, error } = useGetIdentity<{
    workspaces: Workspace[];
  }>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  const workspaces = identity?.workspaces ?? [];

  const [selected, setSelected] = useState<Workspace | undefined>(() => {
    const id = workspaceStore.get();
    return workspaces.find((w) => w.id === id);
  });
  // True for one render cycle after a workspace switch: children are held
  // back so the old workspace's data unmounts before caches reset, so the
  // next paint can never contain the previous workspace's rows.
  const [switching, setSwitching] = useState(false);

  useEffect(() => {
    if (workspaces.length === 0) return;
    const id = workspaceStore.get();
    const found = workspaces.find((w) => w.id === id);
    const next = found ?? workspaces[0];
    workspaceStore.set(next.id);
    setSelected(next);
  }, [workspaces]);

  useEffect(() => {
    if (!switching) return;
    // Runs after the old subtree committed its unmount, so the queries no
    // longer have attached observers and this truly drops them from the
    // cache (removeQueries on a query with active observers would keep the
    // observers serving the old data until the refetch resolves). The new
    // subtree then mounts against empty caches → immediate refetch with the
    // new X-Workspace-ID header, zero stale blip.
    queryClient.removeQueries({ queryKey: ["data", "default"] });
    // useCan results are cached per (resource, action) but depend on the
    // active workspace's role — drop them so permissions re-evaluate against
    // the newly selected workspace.
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] === "access" });
    setSwitching(false);
  }, [switching, queryClient]);

  const value = useMemo<WorkspaceContextValue>(
    () => ({
      workspaces,
      workspace: selected,
      setWorkspace: (w) => {
        if (w.id === selected?.id) return;
        workspaceStore.set(w.id);
        setSelected(w);
        setSwitching(true);
      },
      refresh: () => refetch(),
    }),
    [workspaces, selected, refetch, queryClient],
  );

  // Signed out (e.g. on /login): render children and let the Authenticated
  // guard route to the login flow.
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

  // One render cycle after a workspace switch: old data already unmounted,
  // caches reset, new workspace about to mount — hold the frame.
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
