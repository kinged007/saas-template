import * as React from "react";
import { useParams, Navigate, useNavigate } from "react-router";
import { useCan, useList, type BaseRecord, type HttpError, useCustom, useCustomMutation } from "@refinedev/core";
import { useForm } from "@refinedev/react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { toast } from "sonner";
import { useWatch, type Resolver } from "react-hook-form";

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
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { CreateView, CreateViewHeader } from "@/components/refine-ui/views/create-view";
import type { Agent, AgentSecretInfo, Role } from "@/types";

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
  is_active: z.boolean().optional(),
  skills: z.array(z.string()).optional(),
});

type AgentFormData = z.infer<typeof agentSchema>;

const NULL_AS_LIST = new Set(["mcp_servers", "skills"]);

// Refine's record sync writes raw API nulls into fields; zod rejects nulls on
// submit ("Expected string, received null"), blocking save. Clean them first.
function cleanNulls(value: unknown, key = ""): unknown {
  if (value === null) return NULL_AS_LIST.has(key) ? [] : key === "is_active" || key === "enabled" ? true : "";
  if (Array.isArray(value)) return value.map((item) => cleanNulls(item));
  if (typeof value === "object")
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, cleanNulls(v, k)]));
  return value;
}

const agentResolver: Resolver<AgentFormData> = (values, context, options) =>
  zodResolver(agentSchema)(cleanNulls(values) as AgentFormData, context, options);

const emptyMcp = { id: "", url: "", transport: "http" as const, auth_secret_ref: "", enabled: true, timeout_ms: "" };

export function AgentEditPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: can } = useCan({ resource: "agents", action: "edit" });
  const { result: rolesResult } = useList<Role>({ resource: "roles" });
  const roles = (rolesResult?.data ?? []) as Role[];

  const form = useForm<BaseRecord, HttpError, AgentFormData>({
    resolver: agentResolver,
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
      is_active: true,
      skills: [],
    },
    refineCoreProps: {
      resource: "agents",
      id: id!,
      action: "edit",
      redirect: false,
      successNotification: { message: "Agent updated", type: "success" },
    },
  });

  const {
    refineCore: { query, onFinish, formLoading },
  } = form;
  const record = query?.data?.data as Agent | undefined;

  // Seed the form once. `form` is a new object every render, so depending on it
  // here would re-run this effect → reset → re-render → loop ("Maximum update depth").
  const seededRef = React.useRef(false);
  React.useEffect(() => {
    if (!record || seededRef.current) return;
    seededRef.current = true;
    // Refine's useForm re-applies the raw record (including nulls) to every
    // registered field in a microtask queued by its own effect. Field values
    // of null then fail the zod schema ("Expected string, received null").
    // Queue our reset as a microtask too: refine's effect runs first (hook
    // declared earlier), so its applier is queued first, and our cleaner
    // reset runs last — same task, FIFO ordering.
    queueMicrotask(() => {
      form.reset({
        name: record.name ?? "",
        slug: record.slug ?? "",
        description: record.description ?? "",
        avatar: record.avatar ?? "",
        system_prompt: record.system_prompt ?? "",
        model: record.model ?? "",
        temperature: record.temperature != null ? String(record.temperature) : "",
        max_tokens: record.max_tokens != null ? String(record.max_tokens) : "200000",
        tool_allowlist: record.tool_allowlist ? record.tool_allowlist.join(", ") : "",
        mcp_servers: (record.mcp_servers ?? []).map((m) => ({
          id: m.id,
          url: m.url,
          transport: m.transport as "http" | "sse",
          auth_secret_ref: m.auth_secret_ref ?? "",
          enabled: m.enabled ?? true,
          timeout_ms: m.timeout_ms != null ? String(m.timeout_ms) : "",
        })),
        execution_target: record.execution_target ?? NONE,
        role_id: record.role_id ?? NONE,
        is_active: record.is_active ?? true,
        skills: record.skills ?? [],
      });
    });
  }, [record]);

  const mcpServers = useWatch({ control: form.control, name: "mcp_servers" }) ?? [];
  const nameVal = useWatch({ control: form.control, name: "name" });
  const avatarVal = useWatch({ control: form.control, name: "avatar" });

  // Secrets state
  const { result: secretsResult, query: secretsQuery } = useCustom<{ data: AgentSecretInfo[] } | AgentSecretInfo[]>({
    url: `agents/${id}/secrets`,
    method: "get",
    queryOptions: { enabled: !!id },
  });
  // useCustom may wrap in {data: ...} depending on provider; handle both shapes
  const secrets: AgentSecretInfo[] = React.useMemo(() => {
    if (!secretsResult) return [];
    const raw: unknown = secretsResult.data as unknown;
    if (Array.isArray(raw)) return raw as AgentSecretInfo[];
    if (raw && typeof raw === "object" && "data" in (raw as Record<string, unknown>) && Array.isArray((raw as Record<string, unknown>).data)) {
      return (raw as { data: AgentSecretInfo[] }).data;
    }
    return [];
  }, [secretsResult]);
  const { mutate: putSecret } = useCustomMutation();
  const { mutate: deleteSecret } = useCustomMutation();
  const [newKey, setNewKey] = React.useState("");
  const [newValue, setNewValue] = React.useState("");

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
      is_active: data.is_active,
      skills: data.skills ?? [],
    };
    try {
      await (onFinish as unknown as (v: unknown) => Promise<unknown>)(payload as unknown);
    } catch (err) {
      toast.error("Could not update agent", { description: String((err as { message?: string })?.message ?? err) });
    }
  };

  const handleAddSecret = () => {
    const key = newKey.trim().toUpperCase();
    if (!key || !newValue) {
      toast.error("Key and value are required");
      return;
    }
    if (!/^[A-Z_][A-Z0-9_]*$/.test(key)) {
      toast.error("Key must match ^[A-Z_][A-Z0-9_]*$");
      return;
    }
    putSecret(
      {
        url: `agents/${id}/secrets/${key}`,
        method: "put",
        values: { value: newValue },
        successNotification: false,
        errorNotification: false,
      },
      {
        onSuccess: () => {
          toast.success(`Secret ${key} saved`);
          setNewKey("");
          setNewValue("");
          secretsQuery.refetch();
        },
        onError: (e: unknown) => toast.error(String((e as { message?: string })?.message ?? e)),
      },
    );
  };

  const handleDeleteSecret = (key: string) => {
    deleteSecret(
      {
        url: `agents/${id}/secrets/${key}`,
        method: "delete",
        values: {},
        successNotification: false,
        errorNotification: false,
      },
      {
        onSuccess: () => {
          toast.success(`Secret ${key} deleted`);
          secretsQuery.refetch();
        },
        onError: (e: unknown) => toast.error(String((e as { message?: string })?.message ?? e)),
      },
    );
  };

  return (
    <CreateView>
      <CreateViewHeader title="Edit agent" />
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="flex max-w-2xl flex-col gap-6">
          <div className="flex items-center gap-3">
            <AgentAvatar value={avatarVal} name={nameVal || record?.name || "Agent"} sizeClassName="h-10 w-10" />
            <span className="text-muted-foreground text-xs">Avatar preview</span>
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
              <FormControl><Input {...field} /></FormControl>
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
              <FormControl><Textarea rows={2} {...field} /></FormControl>
              <FormMessage />
            </FormItem>
          )} />

          <FormField control={form.control} name="system_prompt" render={({ field }) => (
            <FormItem>
              <FormLabel>System prompt</FormLabel>
              <FormControl><Textarea rows={5} {...field} /></FormControl>
              <FormMessage />
            </FormItem>
          )} />

          <div className="grid grid-cols-2 gap-4">
            <FormField control={form.control} name="model" render={({ field }) => (
              <FormItem>
                <FormLabel>Model</FormLabel>
                <FormControl><Input placeholder="e.g. anthropic/claude-sonnet" {...field} /></FormControl>
                <FormMessage />
              </FormItem>
            )} />
            <FormField control={form.control} name="execution_target" render={({ field }) => (
              <FormItem>
                <FormLabel>Execution target</FormLabel>
                <Select value={field.value ?? NONE} onValueChange={field.onChange}>
                  <FormControl><SelectTrigger><SelectValue placeholder="No preference" /></SelectTrigger></FormControl>
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
                <FormControl><Input type="number" min={0} max={2} step={0.1} {...field} /></FormControl>
                <FormMessage />
              </FormItem>
            )} />
            <FormField control={form.control} name="max_tokens" render={({ field }) => (
              <FormItem>
                <FormLabel>Max tokens</FormLabel>
                <FormControl><Input type="number" min={1} {...field} /></FormControl>
                <FormMessage />
              </FormItem>
            )} />
          </div>

          <FormField control={form.control} name="is_active" render={({ field }) => (
            <FormItem className="flex items-center gap-2">
              <FormControl><Checkbox checked={!!field.value} onCheckedChange={(c) => field.onChange(c === true)} /></FormControl>
              <FormLabel className="!m-0">Active</FormLabel>
            </FormItem>
          )} />

          <FormField control={form.control} name="role_id" render={({ field }) => (
            <FormItem>
              <FormLabel>Workspace role</FormLabel>
              <Select value={field.value ?? NONE} onValueChange={field.onChange}>
                <FormControl><SelectTrigger><SelectValue /></SelectTrigger></FormControl>
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
            <Button type="submit" disabled={formLoading}>{formLoading ? "Saving…" : "Save"}</Button>
          </div>
        </form>
      </Form>

      <Card className="mt-8 max-w-2xl">
        <CardHeader>
          <CardTitle>Secrets & env</CardTitle>
          <CardDescription>Per-agent env vars stored encrypted via SecretStore. Values are write-only and masked after save.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {secrets.length === 0 ? (
            <p className="text-muted-foreground text-sm">No secrets yet.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {secrets.map((s) => (
                <div key={s.key} className="flex items-center justify-between rounded border px-3 py-2">
                  <div className="flex flex-col">
                    <span className="font-mono text-sm">{s.key}</span>
                    <span className="text-muted-foreground text-xs">{s.created_at ? new Date(s.created_at).toLocaleString() : ""} • ••••••••</span>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => handleDeleteSecret(s.key)}>Delete</Button>
                </div>
              ))}
            </div>
          )}
          <div className="grid grid-cols-12 gap-2">
            <Input className="col-span-4 font-mono" placeholder="ENV_VAR_NAME" value={newKey} onChange={(e) => setNewKey(e.target.value.toUpperCase())} />
            <Input className="col-span-6 font-mono" type="password" placeholder="value" value={newValue} onChange={(e) => setNewValue(e.target.value)} />
            <Button type="button" className="col-span-2" onClick={handleAddSecret}>Add</Button>
          </div>
        </CardContent>
      </Card>
    </CreateView>
  );
}
