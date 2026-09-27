import { useGetIdentity } from "@refinedev/core";
import { useParams } from "react-router";

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
 */
export function UserSettingsLayout() {
  const { id = "" } = useParams();
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });

  const perms = activeWorkspacePermissions(identity);
  const can = (permission?: string) =>
    !permission || perms.includes("*") || perms.includes(permission);

  return (
    <GenericSettingsLayout
      registry={userSettings}
      basePath={`/users/${id}/settings`}
      title="Member Settings"
      subtitle="Edit this member's profile, notifications and security. Workspace memberships are not editable here."
      can={can}
      guard={{
        allowed: identity?.is_superuser === true || can("profile:update"),
        deniedTitle: "Access denied",
        deniedMessage: "Editing another member requires the profile:update permission.",
      }}
    />
  );
}
