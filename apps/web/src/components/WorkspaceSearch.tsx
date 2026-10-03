import { useEffect, useState } from "react";
import { useCustom } from "@refinedev/core";
import { Link } from "react-router";
import { Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { ReadError } from "./ui";
import type { WorkspaceSearchResponse } from "@/types";

function resultLink(r: WorkspaceSearchResponse["results"][number]): string {
  switch (r.type) {
    case "conversation":
    case "message":
      return `/inbox?tab=messages&conversationId=${r.type === "message" ? (r.conversation_id ?? r.id) : r.id}`;
    case "member":
      return "/members";
    case "job":
      return `/jobs/${r.id}`;
    case "notification":
      return "/inbox?tab=notifications";
    default:
      return "/";
  }
}

export function WorkspaceSearch() {
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = window.setTimeout(() => setQ(input.trim()), 300);
    return () => window.clearTimeout(t);
  }, [input]);

  const { result, query } = useCustom<WorkspaceSearchResponse>({
    url: "workspaces/search",
    method: "get",
    config: { query: { q } },
    queryOptions: { enabled: q.length >= 2, retry: false },
  });
  const results = result?.data?.results ?? [];
  const grouped = results.reduce<Record<string, typeof results>>((acc, r) => {
    (acc[r.type] ??= []).push(r);
    return acc;
  }, {});

  return (
    <div className="flex flex-col gap-2">
      <div className="relative">
        <Search className="text-muted-foreground pointer-events-none absolute top-2.5 left-2.5 h-4 w-4" />
        <Input
          placeholder="Search conversations, members, jobs, notifications…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="pl-9"
          aria-label="Search workspace"
        />
      </div>
      {q.length >= 2 && (
        <div className="rounded-lg border p-3">
          <ReadError error={query.error} className="p-0" />
          {query.isPending ? (
            <p className="text-muted-foreground text-sm">Searching…</p>
          ) : results.length === 0 ? (
            <p className="text-muted-foreground text-sm">No results for “{q}”.</p>
          ) : (
            Object.entries(grouped).map(([type, rows]) => (
              <div key={type} className="py-1">
                <p className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">{type}</p>
                {rows.map((r) => (
                  <Link
                    key={`${r.type}-${r.id}`}
                    to={resultLink(r)}
                    className="flex items-center gap-2 rounded px-1 py-1 hover:bg-accent"
                  >
                    <Badge variant="outline" className="font-mono text-xs">{r.type}</Badge>
                    <span className="text-sm font-medium truncate">{r.title ?? r.id.slice(0, 8)}</span>
                    {r.snippet && <span className="text-muted-foreground truncate text-xs">{r.snippet}</span>}
                  </Link>
                ))}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
