import { useMemo } from "react";
import { useCustom, useCustomMutation, useList } from "@refinedev/core";
import { toast } from "sonner";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import type { Notification, NotificationChannel, NotificationPreferences } from "@/types";

const KNOWN_NOTIFICATION_TYPES = [
  "workspace_invitation",
  "member_joined",
  "member_role_changed",
  "member_removed",
] as const;

const CHANNEL_OPTIONS: Array<{ value: NotificationChannel; label: string }> = [
  { value: "in-app", label: "In-app" },
  { value: "email", label: "Email" },
  { value: "off", label: "Off" },
];

export function NotificationPreferencesCard() {
  const { workspace } = useWorkspace();
  const hasWorkspace = Boolean(workspace?.id);
  const { result: notificationsResult } = useList<Notification>({
    resource: "notifications",
    pagination: { pageSize: 200 },
    queryOptions: { enabled: hasWorkspace },
  });
  const { result: preferencesResult, query: preferencesQuery } = useCustom<NotificationPreferences>({
    url: "notifications/preferences",
    method: "get",
  });
  const { mutateAsync: savePreferences, mutation } = useCustomMutation<NotificationPreferences>();
  const preferences = preferencesResult?.data;
  const channels = preferences?.channels ?? {};
  const notificationTypes = useMemo(() => {
    const types = new Set<string>(KNOWN_NOTIFICATION_TYPES);
    for (const notification of notificationsResult?.data ?? []) {
      if (notification.type !== "conversation_message") types.add(notification.type);
    }
    for (const type of Object.keys(channels)) types.add(type);
    return [...types];
  }, [channels, notificationsResult?.data]);

  const save = async (values: Partial<NotificationPreferences>) => {
    try {
      await savePreferences({
        url: "notifications/preferences",
        method: "put",
        values,
        successNotification: false,
        errorNotification: false,
      });
      await preferencesQuery.refetch();
    } catch (error) {
      toast.error((error as { message?: string }).message ?? "Failed to update notification preferences");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Notification preferences</CardTitle>
        <CardDescription>Choose how you receive each type of notification.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {notificationTypes.map((type) => (
          <div key={type} className="flex items-center justify-between gap-4">
            <Label htmlFor={`notification-channel-${type}`} className="font-normal">
              {type}
            </Label>
            <Select
              value={channels[type] ?? "in-app"}
              disabled={mutation.isPending}
              onValueChange={(channel) => void save({ channels: { [type]: channel as NotificationChannel } })}
            >
              <SelectTrigger id={`notification-channel-${type}`} className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CHANNEL_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <Checkbox
            id="daily-digest"
            checked={preferences?.digest_enabled ?? false}
            disabled={mutation.isPending}
            onCheckedChange={(checked) => void save({ digest_enabled: checked === true })}
          />
          <Label htmlFor="daily-digest" className="font-normal">
            Daily digest email (unread summary at 07:00 UTC)
          </Label>
        </div>
      </CardContent>
    </Card>
  );
}
