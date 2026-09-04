import { useCan, useCustom, useList } from "@refinedev/core";
import { Activity, Bot, Coins, Download, Timer, Zap } from "lucide-react";
import { Link } from "react-router";
import { useMemo, useState } from "react";

import { httpClient } from "@/providers/dataProvider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader, EmptyRow, formatDate } from "@/components/ui";
import type { Agent, AgentUsageEntry } from "@/types";

function formatCost(cents: number): string {
  if (!cents) return "$0";
  const dollars = cents / 100;
  return `$${dollars.toFixed(dollars < 0.01 && dollars > 0 ? 6 : 4)}`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function dayKey(iso?: string): string {
  return (iso ?? "").slice(0, 10);
}

/** Token volume per day for the last `days` days, as plain CSS bars. */
function TokenBars({ rows, days = 14 }: { rows: AgentUsageEntry[]; days?: number }) {
  const buckets = useMemo(() => {
    const out: { day: string; tokens: number; runs: number }[] = [];
    const today = new Date();
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(today);
      d.setUTCDate(d.getUTCDate() - i);
      out.push({ day: d.toISOString().slice(0, 10), tokens: 0, runs: 0 });
    }
    const byDay = new Map(out.map((b) => [b.day, b]));
    for (const r of rows) {
      const b = byDay.get(dayKey(r.created_at));
      if (b) {
        b.tokens += r.total_tokens || 0;
        b.runs += 1;
      }
    }
    return out;
  }, [rows, days]);

  const max = Math.max(...buckets.map((b) => b.tokens), 1);
  return (
    <div className="flex h-36 items-end gap-1.5">
      {buckets.map((b) => (
        <div
          key={b.day}
          className="group relative flex min-w-0 flex-1 flex-col items-center justify-end gap-1"
          title={`${b.day}: ${b.tokens} tokens, ${b.runs} run${b.runs === 1 ? "" : "s"}`}
        >
          <div
            className="bg-primary/70 group-hover:bg-primary w-full rounded-sm transition-colors"
            style={{ height: b.tokens ? `${Math.max((b.tokens / max) * 100, 4)}%` : "2px" }}
          />
          <span className="text-muted-foreground text-[10px]">{b.day.slice(8)}</span>
        </div>
      ))}
    </div>
  );
}

export function AgentUsageDashboardPage() {
  const { data: canRead } = useCan({ resource: "agent-usage", action: "list" });

  const [agentId, setAgentId] = useState<string>("all");
  const [status, setStatus] = useState<string>("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const query = useMemo(() => {
    const q: Record<string, string> = { offset: "0", limit: "100" };
    if (agentId !== "all") q.agent_id = agentId;
    if (status !== "all") q.status = status;
    if (from) q.from = from;
    if (to) q.to = to;
    return q;
  }, [agentId, status, from, to]);

  const { result, query: usageQuery } = useCustom<AgentUsageEntry[]>({
    url: "agents/usage",
    method: "get",
    config: { query },
  });
  const { result: agentsResult } = useList<Agent>({
    resource: "agents",
    pagination: { pageSize: 100 },
  });

  const agentName = useMemo(() => {
    const map = new Map<string, string>();
    for (const a of agentsResult?.data ?? []) map.set(a.id, a.name);
    return map;
  }, [agentsResult]);

  const rows = result?.data ?? [];

  const kpis = useMemo(() => {
    const runs = rows.length;
    const tokens = rows.reduce((s, r) => s + (r.total_tokens || 0), 0);
    const cost = rows.reduce((s, r) => s + (r.cost_cents || 0), 0);
    const latencies = rows.map((r) => r.latency_ms || 0);
    const avgLatency = runs ? Math.round(latencies.reduce((s, v) => s + v, 0) / runs) : 0;
    return { runs, tokens, cost, avgLatency };
  }, [rows]);

  const downloadCsv = async () => {
    const params = new URLSearchParams({ ...query, format: "csv" });
    const { data } = await httpClient.get(`agents/usage?${params.toString()}`, {
      responseType: "blob",
    });
    const url = URL.createObjectURL(data);
    const a = document.createElement("a");
    a.href = url;
    a.download = "agent-usage.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  if (canRead?.can === false) {
    return (
      <div className="border-border text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm">
        You don't have permission to view agent usage (agent:usage:read).
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Agent Usage"
        subtitle="Tokens, cost and latency for every agent run in this workspace."
      />

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-muted-foreground text-xs">Agent</span>
          <Select value={agentId} onValueChange={setAgentId}>
            <SelectTrigger className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All agents</SelectItem>
              {(agentsResult?.data ?? []).map((a) => (
                <SelectItem key={a.id} value={a.id}>
                  {a.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-muted-foreground text-xs">Status</span>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="success">Success</SelectItem>
              <SelectItem value="error">Error</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-muted-foreground text-xs">From</span>
          <Input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            className="w-40"
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-muted-foreground text-xs">To</span>
          <Input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            className="w-40"
          />
        </div>
        <Button variant="outline" size="sm" onClick={downloadCsv} className="gap-1.5">
          <Download className="h-4 w-4" /> Export CSV
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-muted-foreground flex items-center gap-2 text-sm font-medium">
              <Activity className="h-4 w-4" /> Runs
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{kpis.runs}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-muted-foreground flex items-center gap-2 text-sm font-medium">
              <Zap className="h-4 w-4" /> Tokens
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatTokens(kpis.tokens)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-muted-foreground flex items-center gap-2 text-sm font-medium">
              <Coins className="h-4 w-4" /> Cost
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatCost(kpis.cost)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-muted-foreground flex items-center gap-2 text-sm font-medium">
              <Timer className="h-4 w-4" /> Avg latency
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {kpis.avgLatency ? `${(kpis.avgLatency / 1000).toFixed(1)}s` : "—"}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Tokens per day (last 14 days)</CardTitle>
        </CardHeader>
        <CardContent>
          <TokenBars rows={rows} />
        </CardContent>
      </Card>

      <div className="border-border overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Agent</TableHead>
              <TableHead>Model</TableHead>
              <TableHead>Tokens</TableHead>
              <TableHead>Cost</TableHead>
              <TableHead>Latency</TableHead>
              <TableHead>Tools</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>When</TableHead>
              <TableHead className="text-right">Thread</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="font-medium">
                  {agentName.get(r.agent_id) ?? (
                    <span className="text-muted-foreground font-mono text-xs">{r.agent_id.slice(0, 8)}…</span>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground text-xs">{r.model || "—"}</TableCell>
                <TableCell className="text-xs">
                  <span className="font-medium">{formatTokens(r.total_tokens)}</span>
                  <span className="text-muted-foreground">
                    {" "}
                    ({r.input_tokens}/{r.output_tokens})
                  </span>
                </TableCell>
                <TableCell className="text-xs">{formatCost(r.cost_cents)}</TableCell>
                <TableCell className="text-muted-foreground text-xs">
                  {r.latency_ms ? `${(r.latency_ms / 1000).toFixed(1)}s` : "—"}
                </TableCell>
                <TableCell className="text-muted-foreground text-xs">{r.tool_calls_count}</TableCell>
                <TableCell>
                  <Badge variant={r.status === "success" ? "success" : "destructive"}>
                    {r.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">{formatDate(r.created_at)}</TableCell>
                <TableCell className="text-right">
                  {r.conversation_id && (
                    <Button asChild variant="ghost" size="sm">
                      <Link
                        to={`/inbox?tab=messages&conversationId=${r.conversation_id}`}
                      >
                        <Bot className="h-4 w-4" /> Open
                      </Link>
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && !usageQuery.isLoading && (
              <EmptyRow colSpan={9}>
                <span className="inline-flex items-center gap-2">
                  <Activity className="h-4 w-4" /> No usage recorded for this filter.
                </span>
              </EmptyRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}