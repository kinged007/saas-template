import { Navigate, Outlet } from "react-router";
import { useGetIdentity } from "@refinedev/core";

import { SettingsNav } from "@/pages/settings/components/SettingsNav";
import { useWorkspace, IDENTITY_QUERY_OPTIONS } from "@/contexts/WorkspaceContext";
import type { Identity } from "@/types";
import { adminSettings } from "../registry";

/** Guard hook for admin sections — layout already blocks non-superusers. */
export function useAdminGuard() {
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  return { identity, isSuperuser: identity?.is_superuser === true };
}

export function AdminLayout() {
  const { data: identity, isLoading } = useGetIdentity<Identity>({
    queryOptions: IDENTITY_QUERY_OPTIONS,
  });
  const { workspace } = useWorkspace();

  // Identity must load first — SidebarNav gates on is_superuser, and the
  // sections disable their queries until then.
  if (isLoading || !identity) {
    return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  }

  if (identity.is_superuser !== true) {
    return (
      <div className="mx-auto max-w-2xl py-12 text-center">
        <h2 className="text-xl font-semibold">Access denied</h2>
        <p className="text-muted-foreground mt-2 text-sm">
          Administration is restricted to superusers.
        </p>
      </div>
    );
  }

  const visibleSections = adminSettings.getVisible(() => true);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Administration</h1>
        <p className="text-muted-foreground text-sm">
          Deployment-wide management across all users and workspaces
          {workspace ? ` — signed in from ${workspace.name}` : ""}.
        </p>
      </div>

      <div className="flex flex-col gap-6 md:flex-row">
        <aside className="w-full shrink-0 md:w-56">
          <SettingsNav sections={visibleSections} basePath="/admin" />
          {__DEV_NOTES__ && (
            <p className="text-muted-foreground mt-4 hidden px-3 text-xs md:block">
              Add tabs by registering sections in <code className="font-mono">admin/registry.ts</code>.
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

/** Index redirect — first registered tab (users). */
export function AdminIndex() {
  const sections = adminSettings.getVisible(() => true);
  return <Navigate to={sections[0]?.key ?? "users"} replace />;
}
