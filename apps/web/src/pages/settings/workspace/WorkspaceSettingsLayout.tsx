import { Link, Navigate, Outlet, useLocation } from "react-router";
import { useGetIdentity } from "@refinedev/core";

import { Button } from "@/components/ui/button";

import { useWorkspace, IDENTITY_QUERY_OPTIONS } from "@/contexts/WorkspaceContext";
import { activeWorkspacePermissions } from "@/utils/permissions";
import type { Identity } from "@/types";
import { workspaceSettings } from "./registry";
import { SettingsNav } from "./components/SettingsNav";
import { isManagerRoleName } from "@/pages/role-name";

function isWorkspaceAdmin(identity: Identity | undefined, workspaceId: string | undefined): boolean {
  if (!identity || !workspaceId) return false;
  if (identity.is_superuser) return true;
  const ws = identity.workspaces.find((w) => w.id === workspaceId);
  if (isManagerRoleName(ws?.role)) return true;
  // Fallback to permission check — admin/owner have workspace:update or audit:read that viewers lack.
  const perms = activeWorkspacePermissions(identity);
  if (perms.includes("*") || perms.includes("workspace:update")) return true;
  return false;
}

export function WorkspaceSettingsLayout() {
  const { workspace } = useWorkspace();
  const {
    data: identity,
    isLoading,
    isError,
    refetch,
  } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  const location = useLocation();

  if (isError) {
    return (
      <div className="mx-auto max-w-2xl py-12 text-center">
        <h2 className="text-xl font-semibold">Couldn't load workspace settings</h2>
        <p className="text-muted-foreground mt-2 text-sm">
          Your account details failed to load. Check your connection and try again.
        </p>
        <div className="mt-4 flex justify-center gap-2">
          <Button onClick={() => refetch()}>Try again</Button>
          <Button variant="outline" asChild>
            <Link to="/">Back to dashboard</Link>
          </Button>
        </div>
      </div>
    );
  }

  if (isLoading || !identity || !workspace) {
    return <p className="text-muted-foreground p-4 text-sm">Loading workspace…</p>;
  }

  const canAccess = isWorkspaceAdmin(identity, workspace.id);

  // Guard: only owners/admins (and superusers) may view workspace settings.
  if (!canAccess) {
    return (
      <div className="mx-auto max-w-2xl py-12 text-center">
        <h2 className="text-xl font-semibold">Access denied</h2>
        <p className="text-muted-foreground mt-2 text-sm">
          You need to be a workspace owner or admin to access workspace settings.
        </p>
        <Button variant="outline" asChild className="mt-4">
          <Link to="/">Back to dashboard</Link>
        </Button>
      </div>
    );
  }

  // Filter sections by the user's permissions in the active workspace.
  const perms = activeWorkspacePermissions(identity);
  const can = (permission?: string) => !permission || perms.includes("*") || perms.includes(permission);
  const visibleSections = workspaceSettings.getVisible(can);

  // If at the index route, redirect to the first visible section (general).
  const isIndex = location.pathname === "/settings/workspace" || location.pathname === "/settings/workspace/";
  if (isIndex && visibleSections.length > 0) {
    return <Navigate to={visibleSections[0].key} replace />;
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Workspace Settings</h1>
        <p className="text-muted-foreground text-sm">
          Manage workspace configuration, roles, jobs, users, and audit history.
          {workspace ? ` — ${workspace.name}` : ""}
        </p>
      </div>

      <div className="flex flex-col gap-6 md:flex-row">
        <aside className="w-full shrink-0 md:w-56">
          <SettingsNav sections={visibleSections} basePath="/settings/workspace" />
          {__DEV_NOTES__ && (
            <p className="text-muted-foreground mt-4 hidden px-3 text-xs md:block">
              Add tabs by registering sections in <code className="font-mono">workspace/registry.ts</code>.
            </p>
          )}
        </aside>

        <div className="min-w-0 flex-1">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
