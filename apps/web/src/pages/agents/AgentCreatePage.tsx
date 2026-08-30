import * as React from "react";
import { useCan, useList, type BaseRecord, type HttpError } from "@refinedev/core";
import { useForm } from "@refinedev/react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { toast } from "sonner";
import { Navigate, useNavigate } from "react-router";
import { useWatch } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { CreateView, CreateViewHeader } from "@/components/refine-ui/views/create-view";
import type { Role } from "@/types";

const NONE = "__none__";

const agentSchema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters").max(150),
  slug: z.string().optional(),
  description: z.string().max(5000).optional().or(z.literal("")),
  avatar: z.string().max(300).optional().or(z.literal("")),
  system_prompt: z.string().optional().or(z.literal("")),
  model: z.string().optional().or(z.literal("")),
  temperature: z.string().optional(),
  max_tokens: z.string().optional(),
  tool_allowlist: z.string().optional(),
  mcp_servers: z.array(
    z.object({
      id: z.string().min(1),
      url: z.string().url("Must be a valid URL"),
      transport: z.enum(["http", "sse"]),
      auth_secret_ref: z.string().optional(),
      enabled: z.boolean(),
      timeout_ms: z.string().optional(),
    }),
  ),
  execution_target: z.string().optional(),
  role_id: z.string().optional(),
  skills: z.array(z.string()).optional(),
});

type AgentFormData = z.infer<typeof agentSchema>;

function slugify(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 100);
}

const emptyMcp = { id: "", url: "", transport: "http" as const, auth_secret_ref: "", enabled: true, timeout_ms: "" };

export function AgentCreatePage() {
  const navigate = useNavigate();
  const { data: can } = useCan({ resource: "agents", action: "create" });
  const { result: rolesResult } = useList<Role>({ resource: "roles" });
  const roles = (rolesResult?.data ?? []) as Role[];

  const form = useForm<BaseRecord, HttpError, AgentFormData>({
    resolver: zodResolver(agentSchema),
    defaultValues: {
      name: "",
      slug: "",
      description: "",
      avatar: "",
      system_prompt: "",
      model: "",
      temperature: "",
      max_tokens: "200000",
      tool_allowlist: "",
      mcp_servers: [],
      execution_target: NONE,
      role_id: NONE,
      skills: [],
    },
    refineCoreProps: {
      resource: "agents",
      action: "create",
      redirect: "list",
      successNotification: { message: "Agent created", type: "success" },
    },
  });

  const {
    refineCore: { onFinish, formLoading },
  } = form;

  const [slugTouched, setSlugTouched] = React.useState(false);
  const nameVal = useWatch({ control: form.control, name: "name" });
  const avatarVal = useWatch({ control: form.control, name: "avatar" });
  const slugVal = useWatch({ control: form.control, name: "slug" });
  const mcpServers = useWatch({ control: form.control, name: "mcp_servers" }) ?? [];

  React.useEffect(() => {
    if (!slugTouched && nameVal) {
      const next = slugify(nameVal);
      if (next && next !== slugVal) form.setValue("slug", next);
    }
  }, [nameVal, slugTouched, slugVal, form]);

  if (can?.can === false) {
    return <Navigate to="/agents" replace />;
  }

  const onSubmit = async (data: AgentFormData) => {
    const payload: Record<string, unknown> = {
      name: data.name,
      slug: data.slug || undefined,
      description: data.description || null,
      avatar: data.avatar || null,
      system_prompt: data.system_prompt || null,
      model: data.model || null,
      temperature: data.temperature === "" || data.temperature === undefined ? null : Number(data.temperature),
      max_tokens: data.max_tokens === "" || data.max_tokens === undefined ? null : Number(data.max_tokens),
      tool_allowlist: data.tool_allowlist ? data.tool_allowlist.split(",").map((s) => s.trim()).filter(Boolean) : null,
      mcp_servers: (data.mcp_servers ?? [])
        .filter((m) => m.id && m.url)
        .map((m) => ({
          id: m.id,
          url: m.url,
          transport: m.transport,
          auth_secret_ref: m.auth_secret_ref || undefined,
          enabled: m.enabled,
          timeout_ms: m.timeout_ms === "" || m.timeout_ms === undefined ? undefined : Number(m.timeout_ms),
        })),
      execution_target: data.execution_target === NONE || !data.execution_target ? null : data.execution_target,
      role_id: data.role_id === NONE ? null : data.role_id || null,
      skills: data.skills ?? [],
    };
    try {
      await (onFinish as unknown as (v: unknown) => Promise<unknown>)(payload as unknown);
    } catch (err) {
      toast.error("Could not create agent", { description: String((err as { message?: string })?.message ?? err) });
    }
  };

  return (
    <CreateView>
      <CreateViewHeader title="Create agent" />
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="flex max-w-2xl flex-col gap-6">
          <div className="flex items-center gap-3">
            <AgentAvatar value={avatarVal} name={nameVal || "Agent"} sizeClassName="h-10 w-10" />
            <span className="text-muted-foreground text-xs">{avatarVal ? "Avatar preview" : "Initials fallback"}</span>
          </div>

          <FormField control={form.control} name="name" render={({ field }) => (
            <FormItem>
              <FormLabel>Name</FormLabel>
              <FormControl><Input placeholder="Support Bot" {...field} /></FormControl>
              <FormMessage />
            </FormItem>
          )} />

          <FormField control={form.control} name="slug" render={({ field }) => (
            <FormItem>
              <FormLabel>Slug</FormLabel>
              <FormControl>
                <Input
                  placeholder="auto-generated from name"
                  {...field}
                  onChange={(e) => { setSlugTouched(true); field.onChange(e); }}
                />
              </FormControl>
              {!slugTouched && nameVal && !field.value && (
                <FormDescription>Will be <code className="font-mono">{slugify(nameVal)}</code></FormDescription>
              )}
              <FormMessage />
            </FormItem>
          )} />

          <FormField control={form.control} name="avatar" render={({ field }) => (
            <FormItem>
              <FormLabel>Avatar</FormLabel>
              <FormControl><Input placeholder="emoji:🤖 | url:https://…" {...field} /></FormControl>
              <FormDescription><code>emoji:🤖</code>, <code>url:https://…</code>, or a bare emoji.</FormDescription>
              <FormMessage />
            </FormItem>
          )} />

          <FormField control={form.control} name="description" render={({ field }) => (
            <FormItem>
              <FormLabel>Description</FormLabel>
              <FormControl><Textarea rows={2} placeholder="What is this agent for?" {...field} /></FormControl>
              <FormMessage />
            </FormItem>
          )} />

          <FormField control={form.control} name="system_prompt" render={({ field }) => (
            <FormItem>
              <FormLabel>System prompt</FormLabel>
              <FormControl><Textarea rows={5} placeholder="You are a helpful assistant…" {...field} /></FormControl>
              <FormMessage />
            </FormItem>
          )} />

          <div className="grid grid-cols-2 gap-4">
            <FormField control={form.control} name="model" render={({ field }) => (
              <FormItem>
                <FormLabel>Model</FormLabel>
                <FormControl><Input placeholder="e.g. anthropic/claude-sonnet" {...field} /></FormControl>
                <FormDescription>Empty = workspace default.</FormDescription>
                <FormMessage />
              </FormItem>
            )} />
            <FormField control={form.control} name="execution_target" render={({ field }) => (
              <FormItem>
                <FormLabel>Execution target</FormLabel>
                <Select value={field.value ?? NONE} onValueChange={field.onChange}>
                  <FormControl><SelectTrigger><SelectValue placeholder="No preference (workspace default)" /></SelectTrigger></FormControl>
                  <SelectContent>
                    <SelectItem value={NONE}>No preference</SelectItem>
                    <SelectItem value="local">local</SelectItem>
                    <SelectItem value="vercel">vercel</SelectItem>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )} />
            <FormField control={form.control} name="temperature" render={({ field }) => (
              <FormItem>
                <FormLabel>Temperature</FormLabel>
                <FormControl><Input type="number" min={0} max={2} step={0.1} placeholder="0.7" {...field} /></FormControl>
                <FormMessage />
              </FormItem>
            )} />
            <FormField control={form.control} name="max_tokens" render={({ field }) => (
              <FormItem>
                <FormLabel>Max tokens</FormLabel>
                <FormControl><Input type="number" min={1} placeholder="4096" {...field} /></FormControl>
                <FormMessage />
              </FormItem>
            )} />
          </div>

          <FormField control={form.control} name="role_id" render={({ field }) => (
            <FormItem>
              <FormLabel>Workspace role</FormLabel>
              <Select value={field.value ?? NONE} onValueChange={field.onChange}>
                <FormControl><SelectTrigger><SelectValue placeholder="No role (no platform access)" /></SelectTrigger></FormControl>
                <SelectContent>
                  <SelectItem value={NONE}>No role</SelectItem>
                  {roles.map((r) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}
                </SelectContent>
              </Select>
              <FormDescription>The agent acts under this role when using platform tools.</FormDescription>
              <FormMessage />
            </FormItem>
          )} />

          <FormField control={form.control} name="tool_allowlist" render={({ field }) => (
            <FormItem>
              <FormLabel>Tool allowlist</FormLabel>
              <FormControl><Input placeholder="web_search, code_exec (comma separated)" {...field} /></FormControl>
              <FormMessage />
            </FormItem>
          )} />

          <FormField
            control={form.control}
            name="mcp_servers"
            render={() => (
              <FormItem>
                <FormLabel>MCP servers</FormLabel>
                <FormDescription>Optional model-context-protocol servers for this agent.</FormDescription>
                <FormControl>
                  <div className="flex flex-col gap-2">
                    {mcpServers.map((s, i) => (
                      <div key={i} className="grid grid-cols-12 gap-2 rounded border p-2">
                        <Input className="col-span-3" placeholder="id" value={s.id} onChange={(e) => form.setValue(`mcp_servers.${i}.id` as never, e.target.value as never)} />
                        <Input className="col-span-5" placeholder="https://…" value={s.url} onChange={(e) => form.setValue(`mcp_servers.${i}.url` as never, e.target.value as never)} />
                        <Select value={s.transport} onValueChange={(v) => form.setValue(`mcp_servers.${i}.transport` as never, v as never)}>
                          <SelectTrigger className="col-span-2"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="http">http</SelectItem>
                            <SelectItem value="sse">sse</SelectItem>
                          </SelectContent>
                        </Select>
                        <Checkbox className="col-span-1 self-center" checked={s.enabled} onCheckedChange={(c) => form.setValue(`mcp_servers.${i}.enabled` as never, (c === true) as never)} />
                        <Button type="button" variant="ghost" size="sm" className="col-span-1" onClick={() => form.setValue("mcp_servers" as never, mcpServers.filter((_, idx) => idx !== i) as never)}>✕</Button>
                      </div>
                    ))}
                    <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => form.setValue("mcp_servers" as never, [...mcpServers, emptyMcp] as never)}>+ Add MCP server</Button>
                  </div>
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => navigate("/agents")}>Cancel</Button>
            <Button type="submit" disabled={formLoading}>{formLoading ? "Creating…" : "Create agent"}</Button>
          </div>
        </form>
      </Form>
    </CreateView>
  );
}
