import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useWorkspaceCustom } from "@/hooks/useWorkspaceQuery";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import type { WorkspaceSearchResponse, WorkspaceSearchResult } from "@/types";

/** The endpoint rejects q outside 2-200 characters, so cap before sending. */
const MAX_QUERY_LENGTH = 200;

function resultLink(r: WorkspaceSearchResult): string {
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

function resultLabel(r: WorkspaceSearchResult): string {
  return r.title ?? r.id.slice(0, 8);
}

/**
 * The sidebar opens this rather than hosting an inline search field, so the
 * query state is reset each time the dialog closes and a reopen starts empty.
 */
export function WorkspaceSearchDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const { workspace } = useWorkspace();
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    if (!open) {
      setInput("");
      setQ("");
    }
  }, [open]);

  useEffect(() => {
    const t = window.setTimeout(() => setQ(input.trim().slice(0, MAX_QUERY_LENGTH)), 300);
    return () => window.clearTimeout(t);
  }, [input]);

  // The dataProvider attaches X-Workspace-ID from the active workspace, so the
  // search is workspace-scoped without the dialog knowing which one is active.
  const { result, query } = useWorkspaceCustom<WorkspaceSearchResponse>({
    url: "workspaces/search",
    method: "get",
    config: { query: { q } },
    errorNotification: false,
    queryOptions: { enabled: q.length >= 2, retry: false },
  });

  const results = result?.data?.results ?? [];
  const grouped = results.reduce<Record<string, WorkspaceSearchResult[]>>((acc, r) => {
    (acc[r.type] ??= []).push(r);
    return acc;
  }, {});

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-hidden p-0 sm:max-w-2xl">
        <DialogTitle className="sr-only">Search workspace</DialogTitle>
        <Command
          // Results come pre-filtered from the server; cmdk's own filtering
          // would additionally hide rows the query already matched.
          shouldFilter={false}
          className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group]:not([hidden])_~[cmdk-group]]:pt-0 [&_[cmdk-input-wrapper]_svg]:h-5 [&_[cmdk-input-wrapper]_svg]:w-5 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-3 [&_[cmdk-item]_svg]:h-5 [&_[cmdk-item]_svg]:w-5"
        >
          <CommandInput
            className="pr-12"
            placeholder="Search conversations, members, jobs, notifications…"
            value={input}
            onValueChange={setInput}
            aria-label="Search workspace"
          />
          <CommandList>
            {!workspace ? (
              <p className="text-muted-foreground p-4 text-center text-sm">Select a workspace to search.</p>
            ) : q.length < 2 ? (
              <p className="text-muted-foreground p-4 text-center text-sm">
                Type at least 2 characters to search.
              </p>
            ) : query.isPending ? (
              <p className="text-muted-foreground p-4 text-center text-sm">Searching…</p>
            ) : query.isError ? (
              <p className="text-destructive p-4 text-center text-sm">
                Search failed: {query.error?.message ?? "please try again."}
              </p>
            ) : (
              <CommandEmpty>No results for “{q}”.</CommandEmpty>
            )}
            {Object.entries(grouped).map(([type, rows]) => (
              <CommandGroup key={type} heading={type.charAt(0).toUpperCase() + type.slice(1)}>
                {rows.map((r) => (
                  <CommandItem
                    key={`${r.type}-${r.id}`}
                    value={`${r.type}-${r.id}`}
                    onSelect={() => {
                      onOpenChange(false);
                      navigate(resultLink(r));
                    }}
                  >
                    <span className="min-w-0 flex-1 truncate font-medium">{resultLabel(r)}</span>
                    {r.snippet && (
                      <span className="text-muted-foreground min-w-0 truncate text-xs">
                        {r.snippet}
                      </span>
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
