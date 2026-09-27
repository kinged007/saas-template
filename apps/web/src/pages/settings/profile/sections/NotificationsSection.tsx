import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  CHANNEL_OPTIONS,
  NOTIFICATION_TYPE_META,
  humanizeType,
  useNotificationPreferences,
} from "@/hooks/useNotificationPreferences";
import type { NotificationChannel } from "@/types";

export function NotificationsSection() {
  const { channels, digestEnabled, visibleTypes, saving, setChannel, setDigest } =
    useNotificationPreferences();

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Notifications</CardTitle>
          <CardDescription>Choose how each notification type reaches you.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {visibleTypes.map((t) => {
            const meta = NOTIFICATION_TYPE_META[t];
            return (
              <div key={t} className="flex items-center justify-between gap-4 border-b py-3 last:border-0">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{meta?.title ?? humanizeType(t)}</p>
                  {meta?.description && (
                    <p className="text-muted-foreground mt-0.5 text-xs">{meta.description}</p>
                  )}
                </div>
                <Select
                  value={channels[t] ?? "in-app"}
                  disabled={saving}
                  onValueChange={(v) => setChannel(t, v as NotificationChannel)}
                >
                  <SelectTrigger className="h-8 w-32 text-sm">
                    <SelectValue>
                      {CHANNEL_OPTIONS.find((o) => o.value === (channels[t] ?? "in-app"))?.label ??
                        (channels[t] ?? "in-app")}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {CHANNEL_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            );
          })}
          <label className="mt-2 flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={digestEnabled}
              disabled={saving}
              onChange={(e) => setDigest(e.target.checked)}
              className="h-3.5 w-3.5 accent-primary"
            />
            Daily digest email (unread summary at 07:00 UTC)
          </label>
        </CardContent>
      </Card>
    </div>
  );
}
