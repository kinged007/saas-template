import { createElement } from "react";
import type { ReactNode } from "react";
import { FileText } from "lucide-react";
import type { MenuItem } from "../components/AppLayout";
import { DemoPage } from "./DemoPage";

/**
 * Project-owned extension seams. A derived project adds a page by editing
 * only this package: append a resource, a route, a menu item, and a
 * permission-map entry here (entity types live in `./types.ts`). The three
 * template-owned integration points (`App.tsx`, `AppLayout.tsx`,
 * `accessControlProvider.ts`) spread these exports in through one-time edits
 * and never change per page afterwards.
 */
export const projectResources = [
  { name: "project-demo", list: "/project-demo", meta: { label: "Project Demo" } },
];

export const projectRoutes: { path: string; element: ReactNode }[] = [
  { path: "project-demo", element: createElement(DemoPage) },
];

export const projectMenuItems: MenuItem[] = [
  { key: "/project-demo", label: "Project Demo", icon: FileText, permission: "member:update" },
];

/**
 * Demo gates on `member:update`: an existing server-side permission held by
 * owner/admin roles but not by editor/viewer roles, so both gating directions
 * are provable with the seeded users (`admin@example.com` vs
 * `user1@example.com` in the same workspace).
 */
export const projectPermissionMap: Record<string, Record<string, string>> = {
  "project-demo": {
    list: "member:update",
  },
};
