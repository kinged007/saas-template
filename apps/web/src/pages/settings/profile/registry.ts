import { User, Bell, ShieldCheck, Briefcase } from "lucide-react";

import { createSettingsRegistry } from "../types";
import { GeneralSection } from "./sections/GeneralSection";
import { NotificationsSection } from "./sections/NotificationsSection";
import { SecuritySection } from "./sections/SecuritySection";
import { WorkspacesSection } from "./sections/WorkspacesSection";

/**
 * Profile settings registry — the single extension seam for user profile pages.
 *
 * How to extend (add a tab without touching layout or routing):
 *
 * ```ts
 * import { profileSettings } from "@/pages/settings/profile/registry";
 * import { MyCustomSection } from "./sections/MyCustomSection";
 *
 * profileSettings.register({
 *   key: "my-tab",
 *   label: "My Tab",
 *   icon: MyIcon,
 *   component: MyCustomSection,
 *   order: 20,
 * });
 * ```
 */
export const profileSettings = createSettingsRegistry([
  {
    key: "general",
    label: "General",
    icon: User,
    component: GeneralSection,
    order: 10,
  },
  {
    key: "notifications",
    label: "Notifications",
    icon: Bell,
    component: NotificationsSection,
    order: 20,
  },
  {
    key: "workspaces",
    label: "Workspaces",
    icon: Briefcase,
    component: WorkspacesSection,
    order: 25,
  },
  {
    key: "security",
    label: "Security",
    icon: ShieldCheck,
    component: SecuritySection,
    order: 30,
  },
]);

export type ProfileSettingsKey = (typeof profileSettings.sections)[number]["key"];
