import { GenericSettingsLayout } from "../components/GenericSettingsLayout";
import { profileSettings } from "./registry";

/**
 * Profile settings shell — header + tab nav on the left, section content on the right.
 * Mirrors WorkspaceSettingsLayout. New tabs register in `profile/registry.ts`.
 */
export function ProfileSettingsLayout() {
  return (
    <GenericSettingsLayout
      registry={profileSettings}
      basePath="/settings/profile"
      title="Profile Settings"
      subtitle="Update your personal information and preferences. Changes are visible to workspace members."
      can={() => true}
    />
  );
}
