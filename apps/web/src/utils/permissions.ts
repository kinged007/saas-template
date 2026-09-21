import type { Identity } from "../types";
import { getActiveWorkspaceId, identityStore, workspaceStore } from "./storage";

/**
 * Permissions for the currently active workspace.
 *
 * Permissions are workspace-scoped: the same user can be an editor in one
 * workspace and a viewer in another. The active workspace is tracked in
 * workspaceStore; its role's permissions are the only ones that apply.
 * Falls back to the identity's top-level permissions (e.g. cached identities
 * fetched before per-workspace permissions existed).
 */
export function activeWorkspacePermissions(identity?: Identity | null): string[] {
  const workspaces = identity?.workspaces ?? [];
  const userId = identity?.id ?? (identityStore.get() as Identity | null)?.id;
  const activeId =
    getActiveWorkspaceId() ?? workspaceStore.get(userId) ?? workspaceStore.get();
  const active = workspaces.find((w) => w.id === activeId) ?? workspaces[0];
  return active?.permissions ?? identity?.permissions ?? [];
}
