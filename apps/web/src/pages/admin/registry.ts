import { Building2, Clock, ScrollText, Users } from "lucide-react";

import { createSettingsRegistry } from "@/pages/settings/types";
import { UsersSection } from "./sections/UsersSection";
import { WorkspacesSection } from "./sections/WorkspacesSection";
import { AuditSection } from "./sections/AuditSection";
import { JobsSection } from "./sections/JobsSection";

/**
 * Admin settings registry — the extension seam for deployment-wide admin tabs.
 * Same pattern as workspace settings: add a tab by registering a section here
 * and adding its route in App.tsx. All tabs are superuser-gated by AdminLayout.
 */
export const adminSettings = createSettingsRegistry([
  {
    key: "users",
    label: "Users",
    icon: Users,
    component: UsersSection,
    order: 10,
  },
  {
    key: "workspaces",
    label: "Workspaces",
    icon: Building2,
    component: WorkspacesSection,
    order: 20,
  },
  {
    key: "audit",
    label: "Audit Log",
    icon: ScrollText,
    component: AuditSection,
    order: 30,
  },
  {
    key: "jobs",
    label: "Jobs",
    icon: Clock,
    component: JobsSection,
    order: 40,
  },
]);
