import { useEffect, useRef, useState } from "react";
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
import { ReadError } from "@/components/ui";
import { errorMessage } from "@/utils/errorMessage";
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
import type { ApiKeyCreated } from "../types";

const apiKeySchema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters"),
  permissions: z.array(z.string()),
  // .max mirrors the backend MAX_QUOTA Integer column ceiling (apps/api/src/models/api_key.py).
  usage_quota: z.number().int().min(1).max(2147483647).nullable().optional(),
  // datetime-local value ("2027-01-01T09:00"), empty = never expires.
  expires_at: z
    .string()
    .nullable()
    .optional()
    .refine(
      (v) => !v || new Date(v).getTime() > Date.now(),
      { message: "Expiry must be in the future" },
    ),
});

type ApiKeyFormData = z.infer<typeof apiKeySchema>;

export function ApiKeyCreatePage() {
  const { list } = useNavigation();
  const { data: can } = useCan({ resource: "api-keys", action: "create" });
  const { result: permissionsResult, query: permissionsQuery } = useCustom<{ permissions: string[] }>({
    url: "api-keys/effective-permissions",
    method: "get",
  });
  const assignable = permissionsResult?.data?.permissions ?? [];

  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);
  // One timer owns the 1.5 s confirmation: a second click restarts it instead of
  // stacking one that ends it early, and it dies with the component.
  const copyTimer = useRef<number | undefined>(undefined);
  const clearCopied = () => {
    window.clearTimeout(copyTimer.current);
    setCopied(false);
  };
  useEffect(() => () => window.clearTimeout(copyTimer.current), []);

  const {
    refineCore: { onFinish, formLoading },
    ...form
  } = useForm<BaseRecord, HttpError, ApiKeyFormData>({
    resolver: zodResolver(apiKeySchema),
    defaultValues: { name: "", permissions: [], usage_quota: null, expires_at: null },
    refineCoreProps: {
      resource: "api-keys",
      action: "create",
      // Stay on the page so the created key can be shown in the dialog below —
      // otherwise refine redirects to the list and the raw key is lost.
      redirect: false,
      errorNotification: false,
      successNotification: {
        message: "API key created",
        description: "Copy the key now — it won't be shown again.",
        type: "success",
      },
    },
  });

  if (can?.can === false) {
    return <Navigate to="/api-keys" replace />;
  }

  const onSubmit = async (data: ApiKeyFormData) => {
    try {
      // The datetime-local input carries no offset; the API requires an aware
      // datetime, so send the browser-local instant as UTC ISO.
      const response = await onFinish({
        ...data,
        expires_at: data.expires_at
          ? new Date(data.expires_at).toISOString()
          : null,
      });
      if (response) {
        setCreated(response.data as ApiKeyCreated);
      }
    } catch (err) {
      toast.error("Could not create API key", {
        description: errorMessage(err),
      });
    }
  };

  const copyKey = async () => {
    if (!created) return;
    // Clear before the write so the previous window dies even if this one never
    // reaches the clipboard.
    window.clearTimeout(copyTimer.current);
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
      copyTimer.current = window.setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      // A denied write must not leave a stale confirmation: the timer above
      // was already cleared, so nothing would reset `copied` (#1216).
      setCopied(false);
      toast.error("Could not copy API key", {
        description: errorMessage(err),
      });
    }
  };

  return (
    <CreateView>
      <CreateViewHeader title="Create API key" />
      <ReadError error={permissionsQuery.error} />
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex max-w-lg flex-col gap-6"
        >
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Name</FormLabel>
                <FormControl>
                  <Input placeholder="ci-deploy" {...field} />
                </FormControl>
                <FormDescription>
                  A short label so you can tell this key apart in the list.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="permissions"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Permissions</FormLabel>
                <FormDescription>
                  You can only grant permissions you have in this workspace.
                </FormDescription>
                <FormControl>
                  <div className="flex max-h-52 flex-col gap-1 overflow-y-auto rounded border p-2">
                    {assignable.length === 0 ? (
                      <p className="text-muted-foreground text-sm">
                        {permissionsQuery.isPending
                          ? 'Loading permissions…'
                          : permissionsQuery.error
                            ? 'Could not load permissions.'
                            : 'No permissions to assign.'}
                      </p>
                    ) : (
                      assignable.map((p) => (
                        <label
                          key={p}
                          className="flex cursor-pointer items-center gap-2 text-sm"
                        >
                          <Checkbox
                            checked={field.value.includes(p)}
                            onCheckedChange={(checked) =>
                              field.onChange(
                                checked
                                  ? [...field.value, p]
                                  : field.value.filter((x) => x !== p),
                              )
                            }
                          />
                          {p}
                        </label>
                      ))
                    )}
                  </div>
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="usage_quota"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Monthly usage quota (optional)</FormLabel>
                <FormControl>
                  <Input
                    type="number"
                    min={1}
                    placeholder="Unlimited"
                    value={field.value ?? ""}
                    onChange={(e) =>
                      field.onChange(e.target.value === "" ? null : Number(e.target.value))
                    }
                  />
                </FormControl>
                <FormDescription>
                  Max authenticated uses per calendar month (UTC). The first window is
                  truncated to the rest of this month. Leave empty for unlimited.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="expires_at"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Expires at (optional)</FormLabel>
                <FormControl>
                  <Input
                    type="datetime-local"
                    value={field.value ?? ""}
                    onChange={(e) => field.onChange(e.target.value || null)}
                  />
                </FormControl>
                <FormDescription>
                  The key stops authenticating at this moment. Leave empty for
                  no expiry.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => list("api-keys")}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={formLoading}>
              {formLoading ? "Creating…" : "Create API key"}
            </Button>
          </div>
        </form>
      </Form>

      <Dialog
        open={created !== null}
        onOpenChange={(open) => {
          if (open) return;
          // The dialog goes away with the key it copies, so the confirmation
          // must not outlive it and greet the next created key.
          clearCopied();
          setCreated(null);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>API key created</DialogTitle>
            <DialogDescription>
              Copy your key now — for security it won't be shown again.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="new-key">Key</Label>
            <div className="flex gap-2">
              <Input
                id="new-key"
                readOnly
                value={created?.key ?? ""}
                className="font-mono"
              />
              <CopyButton
                type="button"
                copied={copied}
                label="Copy API key"
                onClick={copyKey}
              />
            </div>
            {created && created.permissions.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {created.permissions.map((p) => (
                  <Badge key={p} variant="outline" className="text-xs">
                    {p}
                  </Badge>
                ))}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button type="button" onClick={() => list("api-keys")}>
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </CreateView>
  );
}
