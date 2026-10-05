import { useMemo } from "react";
import { useCustom, useCustomMutation } from "@refinedev/core";
import { toast } from "sonner";

import { errorMessage } from "@/utils/errorMessage";

import type { NotificationChannel, NotificationPreferences } from "../types";

export const KNOWN_NOTIFICATION_TYPES = [
  "workspace_invitation",
  "member_joined",
  "member_role_changed",
  "member_removed",
] as const;

export const CHANNEL_OPTIONS: Array<{ value: NotificationChannel; label: string }> = [
  { value: "in-app", label: "In-app" },
  { value: "email", label: "Email" },
  { value: "off", label: "Off" },
];

export const NOTIFICATION_TYPE_META: Record<string, { title: string; description: string }> = {
  workspace_invitation: {
    title: "Workspace invitations",
    description: "When someone invites you to join a workspace.",
  },
  member_joined: {
    title: "New members",
    description: "When someone joins one of your workspaces.",
  },
  member_role_changed: {
    title: "Role changes",
    description: "When your role or another member's role changes.",
  },
  member_removed: {
    title: "Removed members",
    description: "When a member is removed from one of your workspaces.",
  },
};

// ponytail: map covers current backend types; unknown types use humanizeType() until backend ships display names.
/** Fallback for types the frontend doesn't know yet: "some_new_type" → "Some new type". */
export function humanizeType(type: string): string {
  const s = type.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Fetch + update notification delivery preferences. Shared by Inbox and profile settings.
 *
 * `baseUrl` targets another member's preferences for callers holding
 * `profile:update`; it defaults to the signed-in user's own. */
export function useNotificationPreferences(
  extraTypes: string[] = [],
  enabled = true,
  baseUrl = "notifications/preferences"
) {
  const { result: prefsResult, query: prefsQuery } = useCustom<NotificationPreferences>({
    url: baseUrl,
    method: "get",
    queryOptions: { enabled },
  });
  const { mutateAsync: savePrefsAsync, mutation: savePrefsMutation } =
    useCustomMutation<NotificationPreferences>();
  const saving = savePrefsMutation.isPending;
  const prefs = prefsResult?.data;
  const channels = prefs?.channels ?? {};
  const digestEnabled = prefs?.digest_enabled ?? false;
  const visibleTypes = useMemo(() => {
    const seen = new Set<string>(KNOWN_NOTIFICATION_TYPES as unknown as string[]);
    for (const t of extraTypes) seen.add(t);
    for (const t of Object.keys(channels)) seen.add(t);
    return [...seen].filter((t) => t !== "conversation_message");
  }, [extraTypes, channels]);

  const setChannel = async (type: string, channel: NotificationChannel) => {
    try {
      await savePrefsAsync(
        {
          url: baseUrl,
          method: "put",
          values: { channels: { [type]: channel } },
          successNotification: false,
          errorNotification: false,
        },
        { onSuccess: () => prefsQuery.refetch() },
      );
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  const setDigest = async (enabled: boolean) => {
    try {
      await savePrefsAsync(
        {
          url: baseUrl,
          method: "put",
          values: { digest_enabled: enabled },
          successNotification: {
            message: enabled ? "Daily digest enabled" : "Daily digest disabled",
            type: "success",
          },
          errorNotification: false,
        },
        { onSuccess: () => prefsQuery.refetch() },
      );
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  return { channels, digestEnabled, visibleTypes, saving, setChannel, setDigest };
}
