import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { toast } from "sonner";
import { useCustom, useCustomMutation } from "@refinedev/core";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage, FormDescription } from "@/components/ui/form";

const schema = z.object({
  default_model: z.string().max(100).optional().or(z.literal("")),
  default_runner: z.enum(["local", "vercel", "__none__"]),
  memory_enabled: z.boolean(),
  permission_ttl: z.coerce.number().int().min(60).max(86400),
});

type FormData = z.infer<typeof schema>;
const NONE = "__none__";

type Setting = { key: string; value: unknown; updated_at?: string | null };

function unwrap(v: unknown): unknown {
  if (v && typeof v === "object" && "value" in (v as Record<string, unknown>)) {
    const keys = Object.keys(v as object);
    if (keys.length === 1) return (v as { value: unknown }).value;
  }
  return v;
}

export function AgentsGeneralSection() {
  const { result, query } = useCustom<Setting[]>({ url: "workspace-settings", method: "get" });
  const { mutate, mutation } = useCustomMutation();
  const isSaving = mutation.isPending;

  const rows: Setting[] = Array.isArray(result?.data) ? result.data : [];
  const byKey = Object.fromEntries(rows.map((r) => [r.key, unwrap(r.value)]));

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { default_model: "", default_runner: NONE, memory_enabled: false, permission_ttl: 3600 },
  });

  useEffect(() => {
    if (!query.isPending && rows.length >= 0) {
      form.reset({
        default_model: (byKey["agents.default_model"] as string) ?? "",
        default_runner: ((byKey["agents.default_runner"] as string) ?? NONE) as FormData["default_runner"],
        memory_enabled: (byKey["agents.memory_enabled"] as boolean) ?? false,
        permission_ttl: (byKey["agents.permission_ttl"] as number) ?? 3600,
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
      const runner = data.default_runner === NONE ? null : data.default_runner;
      await put("agents.default_model", data.default_model || null);
      await put("agents.default_runner", runner);
      await put("agents.memory_enabled", data.memory_enabled);
      await put("agents.permission_ttl", data.permission_ttl);
      toast.success("Agent settings saved");
      query.refetch();
    } catch (e: unknown) {
      toast.error((e as { message?: string })?.message || "Failed to save");
    }
  };

  if (query.isPending) return <p className="text-muted-foreground text-sm">Loading…</p>;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Agents — General</CardTitle>
        <CardDescription>Workspace defaults used when an agent leaves the field empty. Requires <code>workspace:update</code> to save.</CardDescription>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4">
            <FormField
              control={form.control}
              name="default_model"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Default model</FormLabel>
                  <FormControl>
                    <Input placeholder="e.g. anthropic/claude-sonnet (empty = none)" {...field} />
                  </FormControl>
                  <FormDescription>Used when agent model is null.</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="default_runner"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Default runner</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="No preference" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value={NONE}>No preference</SelectItem>
                      <SelectItem value="local">local</SelectItem>
                      <SelectItem value="vercel">vercel</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="memory_enabled"
              render={({ field }) => (
                <FormItem className="flex items-center gap-3">
                  <FormControl>
                    <Checkbox checked={field.value} onCheckedChange={(v) => field.onChange(v === true)} />
                  </FormControl>
                  <div className="flex flex-col">
                    <FormLabel className="!m-0">Memory enabled</FormLabel>
                    <FormDescription>Enable workspace×agent×user memory retrieval.</FormDescription>
                  </div>
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="permission_ttl"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Permission request TTL (seconds)</FormLabel>
                  <FormControl>
                    <Input type="number" min={60} max={86400} {...field} />
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
