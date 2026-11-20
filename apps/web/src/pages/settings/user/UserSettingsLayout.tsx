import { useGetIdentity } from "@refinedev/core";
import { Navigate, useLocation, useParams } from "react-router";

import { GenericSettingsLayout } from "../components/GenericSettingsLayout";
import { IDENTITY_QUERY_OPTIONS } from "@/contexts/WorkspaceContext";
import { activeWorkspacePermissions } from "@/utils/permissions";
import type { Identity } from "@/types";
import { userSettings } from "./registry";

/**
 * Shell for editing another member (`users/:id/settings/*`).
 *
 * The guard mirrors the backend: `profile:update` in the active workspace, or
 * a deployment admin. The backend stays the authority — this only avoids
 * rendering tabs a request would 403 on.
 *
 * Your own id redirects to the matching self tab: the sections read the target
 * from `useTargetUserId`, which is null on your own id, so this page would
 * render with nothing to edit.
 */
export function UserSettingsLayout() {
  const { id = "" } = useParams();
  // Above the guard: a hook the loading render skips and the resolved render
  // calls changes the hook list on the same fiber.
  const { pathname, search } = useLocation();
  const { data: identity, isLoading } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });

  // The guard reads permissions off identity, so it must not run before
  // /auth/me resolves or a cold load flashes "Access denied" at a caller who
  // is allowed in. Gate before the own-id redirect too: until identity lands
  // `identity?.id` is undefined and the editor shell renders for a target it
  // should be leaving.
  if (isLoading || !identity) {
    return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  }

  const perms = activeWorkspacePermissions(identity);
  const can = (permission?: string) =>
    !permission || perms.includes("*") || perms.includes(permission);

  const requested = pathname.split("/").pop() ?? "";
  if (id && id === identity.id) {
    const tab = userSettings.sections.some((s) => s.key === requested) ? requested : "general";
    return <Navigate to={`/settings/profile/${tab}`} replace />;
  }

  // Entry-point return target, e.g. ?from=/admin/users when opened from the
  // admin users panel. Internal paths only; anything else falls back to the
  // workspace users list. SettingsNav forwards it so tab switches keep it.
  const from = new URLSearchParams(search).get("from");
  const returnTo = from && from.startsWith("/") && !from.startsWith("//") ? from : "/settings/workspace/users";

  return (
    <GenericSettingsLayout
      registry={userSettings}
      basePath={`/users/${id}/settings`}
      title="Member Settings"
      subtitle="Edit this member's profile, notifications and security. Workspace memberships are not editable here."
      can={can}
      backTo={returnTo}
      backLabel={returnTo === "/admin/users" ? "Back to admin users" : "Back to users"}
      guard={{
        allowed: identity.is_superuser === true || can("profile:update"),
        deniedTitle: "Access denied",
        deniedMessage: "Editing another member requires the profile:update permission.",
      }}
    />
  );
}
