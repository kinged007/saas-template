import { Bell, ShieldCheck, User } from "lucide-react";

import { createSettingsRegistry } from "../types";
import { GeneralSection } from "../profile/sections/GeneralSection";
import { NotificationsSection } from "../profile/sections/NotificationsSection";
import { SecuritySection } from "./sections/SecuritySection";

/**
 * Member settings registry — the tabs available when a caller holding
 * `profile:update` edits someone else (`users/:id/settings/*`).
 *
 * General and Notifications are the self-service sections: they read their
 * target from the route (`useTargetUserId`), so the same component serves both
 * pages. A new tab joins by adding an entry here plus its `<Route>` in App.tsx
 * — no layout change.
 *
 * Workspaces is deliberately absent: which workspaces a member belongs to stays
 * a superuser-only view.
 */
export const userSettings = createSettingsRegistry([
  { key: "general", label: "General", icon: User, component: GeneralSection, order: 10 },
  { key: "notifications", label: "Notifications", icon: Bell, component: NotificationsSection, order: 20 },
  { key: "security", label: "Security", icon: ShieldCheck, component: SecuritySection, order: 30 },
]);

export type UserSettingsKey = (typeof userSettings.sections)[number]["key"];
