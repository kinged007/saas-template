import type { AccessControlBindings } from "@refinedev/core";

import { activeWorkspacePermissions } from "../utils/permissions";
import { identityStore } from "../utils/storage";
import type { Identity } from "../types";
import { projectPermissionMap } from "../project";

/** Maps refine (resource, action) to backend permission strings. */
const PERMISSION_MAP: Record<string, Record<string, string>> = {
  workspaces: {
    list: "workspace:read",
    create: "workspace:update",
    edit: "workspace:update",
    delete: "workspace:delete",
    show: "workspace:read",
  },
  members: {
    list: "member:read",
    edit: "member:update",
    delete: "member:delete",
  },
  // Editing another member's profile/notifications/security. Separate from
  // `members.edit` (role management) so a profile editor cannot change roles.
  "member-profiles": {
    show: "member:read",
    edit: "profile:update",
  },
  invitations: {
    list: "member:create",
    create: "member:create",
    delete: "member:delete",
  },
  roles: {
    list: "role:read",
    create: "role:create",
    edit: "role:create",
    show: "role:read",
  },
  "api-keys": {
    list: "apikey:read",
    create: "apikey:create",
    delete: "apikey:delete",
  },
  conversations: {
    list: "message:read",
    create: "message:create",
    edit: "message:create",
    show: "message:read",
  },
  messages: {
    list: "message:read",
    create: "message:create",
    show: "message:read",
  },
  jobs: {
    list: "jobs:read",
    show: "jobs:read",
    edit: "jobs:update",
  },
  webhooks: {
    list: "webhook:read",
    create: "webhook:create",
    edit: "webhook:update",
    delete: "webhook:delete",
  },
  audit: {
    list: "audit:read",
    show: "audit:read",
  },
  ...projectPermissionMap,
};

export const accessControlProvider: AccessControlBindings = {
  can: async ({ resource, action }) => {
    // Inbox messaging (notifications / conversations / messages) is always available to session users.
    // Only API keys are gated on their own permission list; the backend enforces that.
    // Return true here so the UI (Inbox, Compose) is never hidden by role permissions.
    if (resource === "notifications" || resource === "conversations" || resource === "messages") {
      return { can: true };
    }
    const identity = identityStore.get() as Identity | null;
    const permissions = activeWorkspacePermissions(identity);
    const actionKey = action ?? "";
    const required = resource ? PERMISSION_MAP[resource]?.[actionKey] : undefined;
    if (!required) {
      return { can: true };
    }
    return { can: permissions.includes("*") || permissions.includes(required) };
  },
};
