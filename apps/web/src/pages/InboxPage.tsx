import { useEffect, useMemo, useRef, useState } from "react";
import { useList, useUpdate } from "@refinedev/core";
import Markdown from "react-markdown";
import { ArrowLeft, Inbox, Mail, MailOpen, ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useWorkspace } from "../contexts/WorkspaceContext";
import { formatDate } from "../components/ui";
import { PageHeader } from "../components/refine-ui/layout/page-header";
import { cn } from "@/lib/utils";
import type { Notification } from "../types";

type StatusFilter = "unread" | "read" | "all";

const STATUS_OPTIONS: Array<{ value: StatusFilter; label: string }> = [
  { value: "unread", label: "Unread" },
  { value: "read", label: "Read" },
  { value: "all", label: "All" },
];

function truncate(text: string | undefined, max: number): string {
  if (!text) return "";
  return text.length > max ? text.slice(0, max) + "…" : text;
}

export function InboxPage() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("unread");
  const [workspaceFilter, setWorkspaceFilter] = useState<string>("all");
  const [selected, setSelected] = useState<Notification | null>(null);
  const { workspace } = useWorkspace();
  const selectedRef = useRef<Notification | null>(null);
  const openedAtRef = useRef(0);
  const pendingTimerRef = useRef<number | null>(null);

  const { result } = useList<Notification>({
    resource: "notifications",
    pagination: { pageSize: 200 },
    sorters: [{ field: "created_at", order: "desc" }],
    filters:
      statusFilter === "all"
        ? []
        : [
            {
              field: "acknowledged",
              operator: "eq",
              value: statusFilter === "unread" ? "false" : "true",
            },
          ],
  });
  const { mutate: updateOne } = useUpdate();

  const allItems = result?.data ?? [];

  const workspaceFilterOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const n of allItems) {
      if (n.workspace_id && !seen.has(n.workspace_id)) {
        seen.set(n.workspace_id, n.workspace_name || "Unknown");
      }
    }
    return Array.from(seen.entries()).map(([id, name]) => ({ id, name }));
  }, [allItems]);

  const items = useMemo(() => {
    let filtered = allItems;
    if (workspaceFilter !== "all") {
      filtered = filtered.filter((n) => n.workspace_id === workspaceFilter);
    }
    const currentWs: Notification[] = [];
    const otherWs: Notification[] = [];
    for (const n of filtered) {
      if (!n.workspace_id || n.workspace_id === workspace?.id) {
        currentWs.push(n);
      } else {
        otherWs.push(n);
      }
    }
    return [...currentWs, ...otherWs];
  }, [allItems, workspaceFilter, workspace?.id]);

  const markRead = (id: string) =>
    updateOne({
      resource: "notifications",
      id,
      values: { acknowledged: true },
      successNotification: false,
    });

  const markUnread = (id: string) =>
    updateOne({
      resource: "notifications",
      id,
      values: { acknowledged: false },
      successNotification: false,
    });

  const clearPendingTimer = () => {
    if (pendingTimerRef.current !== null) {
      window.clearTimeout(pendingTimerRef.current);
      pendingTimerRef.current = null;
    }
  };

  const scheduleMarkRead = (id: string, openedAt: number) => {
    clearPendingTimer();
    const delay = Math.max(0, 3000 - (Date.now() - openedAt));
    pendingTimerRef.current = window.setTimeout(() => {
      markRead(id);
      pendingTimerRef.current = null;
    }, delay);
  };

  const exitCurrent = () => {
    const cur = selectedRef.current;
    if (cur && !cur.acknowledged) {
      scheduleMarkRead(cur.id, openedAtRef.current);
    }
    selectedRef.current = null;
  };

  const handleSelect = (n: Notification) => {
    if (n.id === selectedRef.current?.id) return;
    exitCurrent();
    openedAtRef.current = Date.now();
    selectedRef.current = n;
    setSelected(n);
  };

  const handleClose = () => {
    exitCurrent();
    setSelected(null);
  };

  useEffect(() => {
    return () => {
      const cur = selectedRef.current;
      if (cur && !cur.acknowledged) {
        scheduleMarkRead(cur.id, openedAtRef.current);
      }
    };
  }, []);

  const toggleAck = () => {
    const cur = selectedRef.current;
    if (!cur) return;
    const next = { ...cur, acknowledged: !cur.acknowledged };
    setSelected(next);
    if (next.acknowledged) {
      markRead(cur.id);
    } else {
      markUnread(cur.id);
    }
  };

  const linkUrl = (n: Notification) =>
    (n.payload as Record<string, unknown> | undefined)?.url as string | undefined;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        title="Inbox"
        actions={
          <>
            <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as StatusFilter)}>
              <SelectTrigger className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={workspaceFilter} onValueChange={setWorkspaceFilter}>
              <SelectTrigger className="w-44">
                <SelectValue placeholder="All workspaces" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All workspaces</SelectItem>
                {workspaceFilterOptions.map((w) => (
                  <SelectItem key={w.id} value={w.id}>
                    {w.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </>
        }
      />

      <div className="flex min-h-0 flex-1 overflow-hidden rounded-lg border">
        <div
          className={cn(
            "border-border flex w-full flex-col overflow-y-auto border-r md:w-80",
            selected ? "hidden md:flex" : "flex",
          )}
        >
          {items.map((n) => {
            const isActive = n.id === selected?.id;
            return (
              <button
                key={n.id}
                type="button"
                onClick={() => handleSelect(n)}
                className={cn(
                  "border-border flex flex-col gap-1 border-b px-4 py-3 text-left transition-colors",
                  isActive ? "bg-accent" : "hover:bg-accent/50",
                )}
              >
                <div className="flex items-center gap-2">
                  {!n.acknowledged && (
                    <span className="bg-primary mt-1 h-2 w-2 shrink-0 rounded-full" />
                  )}
                  <p
                    className={cn(
                      "min-w-0 flex-1 truncate text-sm",
                      !n.acknowledged ? "font-semibold" : "font-medium",
                    )}
                  >
                    {n.title}
                  </p>
                  {n.workspace_id && n.workspace_id !== workspace?.id && (
                    <Badge variant="outline" className="shrink-0 text-[10px]">
                      {n.workspace_name || "Workspace"}
                    </Badge>
                  )}
                </div>
                <p className="text-muted-foreground line-clamp-1 pl-4 text-xs">
                  {truncate(n.body, 100)}
                </p>
                <p className="text-muted-foreground pl-4 text-[11px]">
                  {formatDate(n.created_at)}
                </p>
              </button>
            );
          })}
          {items.length === 0 && (
            <div className="flex flex-1 items-center justify-center p-6">
              <p className="text-muted-foreground text-sm">No notifications.</p>
            </div>
          )}
        </div>

        <div
          className={cn(
            "flex min-w-0 flex-1 flex-col overflow-y-auto",
            selected ? "flex" : "hidden md:flex",
          )}
        >
          {selected ? (
            <div className="flex flex-1 flex-col p-6">
              <div className="mb-4 flex items-center gap-3 md:hidden">
                <Button size="sm" variant="ghost" onClick={handleClose}>
                  <ArrowLeft className="mr-1 h-4 w-4" />
                  Back
                </Button>
              </div>
              <div className="mb-6 flex flex-col gap-2">
                <h3 className="text-xl font-semibold">{selected.title}</h3>
                <div className="text-muted-foreground flex flex-wrap items-center gap-3 text-sm">
                  <span>{formatDate(selected.created_at)}</span>
                  {selected.workspace_name && (
                    <>
                      <span>·</span>
                      <Badge variant="secondary">{selected.workspace_name}</Badge>
                    </>
                  )}
                </div>
              </div>
              <div className="prose prose-sm dark:prose-invert max-w-none flex-1">
                <Markdown>{selected.body || ""}</Markdown>
              </div>
              <div className="border-border mt-6 flex items-center gap-2 border-t pt-4">
                {linkUrl(selected) && (
                  <Button size="sm" variant="outline" asChild>
                    <a href={linkUrl(selected)} target="_blank" rel="noopener noreferrer">
                      <ExternalLink className="mr-1 h-3.5 w-3.5" />
                      Open link
                    </a>
                  </Button>
                )}
<Button size="sm" variant="ghost" onClick={toggleAck}>
                  {selected.acknowledged ? (
                    <>
                      <Mail className="mr-1 h-3.5 w-3.5" />
                      Mark as unread
                    </>
                  ) : (
                    <>
                      <MailOpen className="mr-1 h-3.5 w-3.5" />
                      Mark as read
                    </>
                  )}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center">
              <div className="text-center">
                <Inbox className="text-muted-foreground/40 mx-auto h-12 w-12" />
                <p className="text-muted-foreground mt-3 text-sm">
                  Select a notification to read
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
