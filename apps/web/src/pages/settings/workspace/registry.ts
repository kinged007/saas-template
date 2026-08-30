import { Building2, Users, ShieldCheck, Clock, ScrollText, Bot, Container } from "lucide-react";

import { createSettingsRegistry } from "../types";
import { GeneralSection } from "./sections/GeneralSection";
import { RolesSection } from "./sections/RolesSection";
import { JobsSection } from "./sections/JobsSection";
import { UsersSection } from "./sections/UsersSection";
import { AuditLogSection } from "./sections/AuditLogSection";
import { AgentsGeneralSection } from "./sections/AgentsGeneralSection";
import { AgentsSandboxSection } from "./sections/AgentsSandboxSection";

/**
 * Workspace settings registry — the single extension seam for workspace admin pages.
 *
 * How to extend (different entity types / different projects):
 *
 * ```ts
 * import { workspaceSettings } from "@/pages/settings/workspace/registry";
 * import { MyCustomSection } from "./sections/MyCustomSection";
 *
 * // Add a new tab to workspace settings without touching layout or routing:
 * workspaceSettings.register({
 *   key: "my-tab",
 *   label: "My Tab",
 *   icon: MyIcon,
 *   component: MyCustomSection,
 *   permission: "my:read",  // optional — hidden when permission missing
 *   order: 60,
 * });
 * ```
 *
 * For a completely different entity (e.g. org, project), create a new registry:
 * ```ts
 * export const projectSettings = createSettingsRegistry([
 *   { key: "general", label: "General", component: ProjectGeneral, order: 10 },
 * ]);
 * ```
 * and pair it with `SettingsLayout` (the generic shell) or a copy of
 * `WorkspaceSettingsLayout`.
 */
export const workspaceSettings = createSettingsRegistry([
  {
    key: "general",
    label: "General",
    icon: Building2,
    component: GeneralSection,
    order: 10,
    // visible to anyone who can view workspace; edits are gated inside the form by workspace:update
  },
  {
    key: "roles",
    label: "Roles",
    icon: ShieldCheck,
    component: RolesSection,
    permission: "role:read",
    order: 20,
  },
  {
    key: "jobs",
    label: "Jobs",
    icon: Clock,
    component: JobsSection,
    permission: "jobs:view",
    order: 30,
  },
  {
    key: "users",
    label: "Users",
    icon: Users,
    component: UsersSection,
    permission: "member:read",
    order: 40,
  },
  {
    key: "audit",
    label: "Audit Log",
    icon: ScrollText,
    component: AuditLogSection,
    permission: "audit:read",
    order: 50,
  },
  {
    key: "agents-general",
    label: "Agents",
    icon: Bot,
    component: AgentsGeneralSection,
    permission: "workspace:read",
    order: 60,
  },
  {
    key: "agents-sandbox",
    label: "Sandbox",
    icon: Container,
    component: AgentsSandboxSection,
    permission: "workspace:read",
    order: 61,
  },
]);

export type WorkspaceSettingsKey = (typeof workspaceSettings.sections)[number]["key"];
