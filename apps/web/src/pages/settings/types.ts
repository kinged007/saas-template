import type { LucideIcon } from "lucide-react";
import type { ComponentType } from "react";

/**
 * Generic settings-section contract.
 *
 * Intended as the extension seam for the whole settings system:
 * - Add a new workspace tab by pushing an entry to the workspace registry.
 * - Add settings for a different entity type (e.g. project, org) by calling
 *   `createSettingsRegistry()` with its own sections — no layout changes needed.
 * - Forks replace or extend a project-specific registry file without touching
 *   layout or routing.
 */
export type SettingsSection = {
  /** URL slug / key for this tab (e.g. "general", "roles"). Must be unique. */
  key: string;
  /** Human-readable label shown in the nav. */
  label: string;
  /** Optional icon shown next to the label. */
  icon?: LucideIcon;
  /** Component rendered when this tab is active. */
  component: ComponentType;
  /** Refine permission required to see this tab (e.g. "audit:read"). */
  permission?: string;
  /** Sort weight — lower renders first. Defaults to 100. */
  order?: number;
  /** When false the section is hidden from nav but still routable. */
  visible?: boolean;
};

export type SettingsRegistry = {
  sections: SettingsSection[];
  register: (section: SettingsSection) => void;
  getVisible: (can: (permission?: string) => boolean) => SettingsSection[];
  getByKey: (key: string) => SettingsSection | undefined;
};

/**
 * Factory for an extensible settings registry.
 *
 * ```ts
 * // workspace/registry.ts
 * export const workspaceSettings = createSettingsRegistry([
 *   { key: "general", label: "General", component: GeneralSection, order: 10 },
 *   { key: "custom",  label: "My Tab",  component: MySection, permission: "custom:read" },
 * ]);
 *
 * // For another entity:
 * export const projectSettings = createSettingsRegistry([...]);
 * ```
 */
export function createSettingsRegistry(initial: SettingsSection[] = []): SettingsRegistry {
  const sections: SettingsSection[] = [...initial].sort((a, b) => (a.order ?? 100) - (b.order ?? 100));

  return {
    get sections() {
      return [...sections].sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
    },
    register(section: SettingsSection) {
      const idx = sections.findIndex((s) => s.key === section.key);
      if (idx >= 0) sections[idx] = section;
      else sections.push(section);
      sections.sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
    },
    getVisible(can) {
      return sections
        .filter((s) => s.visible !== false)
        .filter((s) => can(s.permission))
        .sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
    },
    getByKey(key) {
      return sections.find((s) => s.key === key);
    },
  };
}
