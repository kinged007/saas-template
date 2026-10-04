import { useState } from "react";
import {
  useCan,
  useCustom,
  useNavigation,
  type BaseRecord,
  type HttpError,
} from "@refinedev/core";
import { useForm } from "@refinedev/react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Navigate } from "react-router";
import { toast } from "sonner";

import { CopyButton } from "@/components/CopyButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  CreateView,
  CreateViewHeader,
} from "../components/refine-ui/views/create-view";
import type { WebhookSubscriptionCreated } from "../types";

const webhookSchema = z.object({
  url: z.string().url("Must be a valid URL"),
  events: z.array(z.string()).min(1, "Select at least one event"),
});

type WebhookFormData = z.infer<typeof webhookSchema>;

export function WebhookCreatePage() {
  const { list } = useNavigation();
  const { data: can } = useCan({ resource: "webhooks", action: "create" });
  const { result: eventsResult } = useCustom<{ events: string[] }>({
    url: "webhooks/events",
    method: "get",
  });
  const available = eventsResult?.data?.events ?? [];

  const [created, setCreated] = useState<WebhookSubscriptionCreated | null>(null);
  const [copied, setCopied] = useState(false);

  const {
    refineCore: { onFinish, formLoading },
    ...form
  } = useForm<BaseRecord, HttpError, WebhookFormData>({
    resolver: zodResolver(webhookSchema),
    defaultValues: { url: "", events: [] },
    refineCoreProps: {
      resource: "webhooks",
      action: "create",
      redirect: false,
      errorNotification: false,
      successNotification: {
        message: "Webhook created",
        description: "Copy the signing secret now — it won't be shown again.",
        type: "success",
      },
    },
  });

  if (can?.can === false) {
    return <Navigate to="/webhooks" replace />;
  }

  const onSubmit = async (data: WebhookFormData) => {
    try {
      const response = await onFinish(data);
      if (response) {
        setCreated(response.data as WebhookSubscriptionCreated);
      }
    } catch (err) {
      toast.error("Could not create webhook", {
        description: String((err as { message?: string })?.message ?? err),
      });
    }
  };

  const toggleEvent = (event: string, checked: boolean) => {
    const current = form.getValues("events");
    form.setValue(
      "events",
      checked ? [...current, event] : current.filter((e) => e !== event),
      { shouldValidate: true },
    );
  };

  return (
    <CreateView>
      <CreateViewHeader title="Create webhook" />
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex max-w-lg flex-col gap-6"
        >
          <FormField
            control={form.control}
            name="url"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Target URL</FormLabel>
                <FormControl>
                  <Input placeholder="https://example.com/hooks/acme" {...field} />
                </FormControl>
                <FormDescription>
                  HTTPS in production. Private hosts are rejected.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="events"
            render={() => (
              <FormItem>
                <FormLabel>Events</FormLabel>
                <div className="flex flex-col gap-2">
                  {available.map((event) => (
                    <div key={event} className="flex items-center gap-2">
                      <Checkbox
                        id={`event-${event}`}
                        checked={form.watch("events").includes(event)}
                        onCheckedChange={(checked) =>
                          toggleEvent(event, checked === true)
                        }
                      />
                      <Label
                        htmlFor={`event-${event}`}
                        className="font-mono text-xs"
                      >
                        {event}
                      </Label>
                    </div>
                  ))}
                  {available.length === 0 && (
                    <p className="text-muted-foreground text-sm">
                      Loading events…
                    </p>
                  )}
                </div>
                <FormMessage />
              </FormItem>
            )}
          />
          <div>
            <Button type="submit" disabled={formLoading}>
              Create webhook
            </Button>
          </div>
        </form>
      </Form>
      <Dialog open={created !== null} onOpenChange={() => list("webhooks")}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Signing secret</DialogTitle>
            <DialogDescription>
              Copy the secret now — it is never shown again. Verify deliveries
              with HMAC-SHA256 over{" "}
              <code>timestamp + &quot;.&quot; + raw_body</code> (
              <code>X-Webhook-Signature: sha256=&lt;hex&gt;</code>).
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="font-mono text-xs break-all">
              {created?.secret}
            </Badge>
            <CopyButton
              copied={copied}
              label="Copy signing secret"
              size="sm"
              onClick={async () => {
                if (!created) return;
                await navigator.clipboard.writeText(created.secret);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            />
          </div>
          <DialogFooter>
            <Button onClick={() => list("webhooks")}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </CreateView>
  );
}
