import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { toast } from "sonner";
import { useCustom, useCustomMutation } from "@refinedev/core";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage, FormDescription } from "@/components/ui/form";

const schema = z.object({
  team_id: z.string().max(100).optional().or(z.literal("")),
  token: z.string().max(10000).optional().or(z.literal("")),
  timeout_seconds: z.coerce.number().int().min(1).max(3600).optional(),
});

type FormData = z.infer<typeof schema>;
type Setting = { key: string; value: unknown };

function unwrap(v: unknown): unknown {
  if (v && typeof v === "object" && "value" in (v as Record<string, unknown>)) {
    const keys = Object.keys(v as object);
    if (keys.length === 1) return (v as { value: unknown }).value;
  }
  return v;
}

export function AgentsSandboxSection() {
  const { result, query } = useCustom<Setting[]>({ url: "workspace-settings", method: "get" });
  const { mutate, mutation } = useCustomMutation();
  const [deleting, setDeleting] = useState(false);
  const isSaving = mutation.isPending;

  const rows: Setting[] = Array.isArray(result?.data) ? result.data : [];
  const byKey = Object.fromEntries(rows.map((r) => [r.key, r.value]));
  const hasToken = (byKey["agents.sandbox.vercel_token"] as { has_value?: boolean } | undefined)?.has_value ?? false;

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { team_id: "", token: "", timeout_seconds: undefined },
  });

  useEffect(() => {
    if (!query.isPending) {
      form.reset({
        team_id: (unwrap(byKey["agents.sandbox.vercel_team_id"]) as string) ?? "",
        token: "",
        timeout_seconds: (unwrap(byKey["agents.sandbox.timeout_seconds"]) as number) ?? undefined,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query.isPending, JSON.stringify(byKey)]);

  const put = (key: string, value: unknown) =>
    new Promise<void>((resolve, reject) => {
      mutate(
        { url: `workspace-settings/${key}`, method: "put", values: { value }, successNotification: false, errorNotification: false },
        { onSuccess: () => resolve(), onError: (e: unknown) => reject(e) },
      );
    });

  const onSubmit = async (data: FormData) => {
    try {
      await put("agents.sandbox.vercel_team_id", data.team_id || null);
      if (data.token) await put("agents.sandbox.vercel_token", data.token);
      if (data.timeout_seconds !== undefined && data.timeout_seconds !== null && String(data.timeout_seconds) !== "") {
        await put("agents.sandbox.timeout_seconds", Number(data.timeout_seconds));
      }
      toast.success("Sandbox settings saved");
      form.setValue("token", "");
      query.refetch();
    } catch (e: unknown) {
      toast.error((e as { message?: string })?.message || "Failed to save");
    }
  };

  const onDeleteToken = () => {
    setDeleting(true);
    mutate(
      { url: "workspace-settings/agents.sandbox.vercel_token", method: "delete", values: {}, successNotification: false, errorNotification: false },
      {
        onSuccess: () => {
          toast.success("Token deleted");
          query.refetch();
          setDeleting(false);
        },
        onError: (e: unknown) => {
          toast.error((e as { message?: string })?.message || "Delete failed");
          setDeleting(false);
        },
      },
    );
  };

  if (query.isPending) return <p className="text-muted-foreground text-sm">Loading…</p>;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Agents — Sandbox</CardTitle>
        <CardDescription>Vercel Sandbox credentials and runner limits. Token is encrypted at rest and write-only.</CardDescription>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4">
            <FormField
              control={form.control}
              name="team_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Vercel team ID</FormLabel>
                  <FormControl>
                    <Input placeholder="team_… (optional)" {...field} />
                  </FormControl>
                  <FormDescription>Optional Vercel team scope.</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="token"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Vercel token {hasToken && <span className="text-muted-foreground font-normal">(has value • write to replace)</span>}</FormLabel>
                  <FormControl>
                    <Input type="password" placeholder={hasToken ? "•••••••• (leave empty to keep)" : "vercel token"} {...field} />
                  </FormControl>
                  <FormDescription>Stored encrypted; never returned in GET.</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            {hasToken && (
              <div className="flex justify-start">
                <Button type="button" variant="outline" size="sm" disabled={deleting} onClick={onDeleteToken}>
                  {deleting ? "Deleting…" : "Delete token"}
                </Button>
              </div>
            )}
            <FormField
              control={form.control}
              name="timeout_seconds"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Runner timeout (seconds)</FormLabel>
                  <FormControl>
                    <Input type="number" min={1} max={3600} placeholder="e.g. 600" {...field} value={field.value ?? ""} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <div className="flex justify-end">
              <Button type="submit" disabled={isSaving}>
                {isSaving ? "Saving…" : "Save"}
              </Button>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}
