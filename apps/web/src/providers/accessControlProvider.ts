import type { AccessControlBindings } from "@refinedev/core";

import { activeWorkspacePermissions } from "../utils/permissions";
import { identityStore } from "../utils/storage";
import type { Identity } from "../types";

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
    edit: "member:manage",
    delete: "member:manage",
  },
  invitations: {
    list: "member:invite",
    create: "member:invite",
    delete: "member:invite",
  },
  roles: {
    list: "role:read",
    create: "role:manage",
    show: "role:read",
  },
  "api-keys": {
    list: "apikey:read",
    create: "apikey:manage",
    delete: "apikey:manage",
  },
  notifications: {
    list: "notification:read",
    edit: "notification:acknowledge",
  },
  conversations: {
    list: "message:read",
    create: "message:send",
    edit: "message:send",
    show: "message:read",
  },
  messages: {
    list: "message:read",
    create: "message:send",
    show: "message:read",
  },
  jobs: {
    list: "jobs:view",
    show: "jobs:view",
    edit: "jobs:edit",
  },
  audit: {
    list: "audit:read",
    show: "audit:read",
  },
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
