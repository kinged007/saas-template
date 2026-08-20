import { useEffect, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Bell, ExternalLink, Inbox } from "lucide-react";
import { useList, useUpdate } from "@refinedev/core";
import { useNavigate } from "react-router";

import type { Notification } from "../types";
import { useWorkspace } from "../contexts/WorkspaceContext";
import { formatDate } from "./ui";

function truncate(text: string | undefined, max: number): string {
  if (!text) return "";
  return text.length > max ? text.slice(0, max) + "…" : text;
}

function workspaceName(n: Notification): string {
  return n.workspace_name || "Unknown workspace";
}

export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const { result, query } = useList<Notification>({
    resource: "notifications",
    pagination: { pageSize: 20 },
    sorters: [{ field: "created_at", order: "desc" }],
    filters: [{ field: "acknowledged", operator: "eq", value: "false" }],
  });
  const { mutate } = useUpdate();
  const { workspace, workspaces, setWorkspace } = useWorkspace();
  const navigate = useNavigate();

  const items = result?.data ?? [];
  const unread = result?.total ?? items.length;

  useEffect(() => {
    if (open) query.refetch();
  }, [open, query]);

  const acknowledge = (id: string) => {
    mutate(
      { resource: "notifications", id, values: { acknowledged: true } },
      { onSuccess: () => query.refetch() },
    );
  };

  const linkUrl = (n: Notification) =>
    (n.payload as Record<string, unknown> | undefined)?.url as string | undefined;

  const canOpen = (n: Notification) => {
    if (!linkUrl(n)) return false;
    if (!n.workspace_id || n.workspace_id === workspace?.id) return true;
    return workspaces.some((w) => w.id === n.workspace_id);
  };

  const openNotification = (n: Notification) => {
    const url = linkUrl(n);
    if (!url) return;
    if (n.workspace_id && n.workspace_id !== workspace?.id) {
      const target = workspaces.find((w) => w.id === n.workspace_id);
      if (!target) return;
      setOpen(false);
      setWorkspace(target);
    }
    setOpen(false);
    navigate(url);
  };

  const current: Notification[] = [];
  const others = new Map<string, Notification[]>();
  for (const n of items) {
    if (!n.workspace_id || n.workspace_id === workspace?.id) {
      current.push(n);
    } else {
      const bucket = others.get(n.workspace_id) ?? [];
      bucket.push(n);
      others.set(n.workspace_id, bucket);
    }
  }

  const renderItem = (n: Notification) => {
    const url = linkUrl(n);
    return (
      <div key={n.id} className="border-border flex flex-col gap-2 rounded-lg border p-3">
        <p className="text-sm font-semibold">{n.title}</p>
        {n.body && (
          <p className="text-muted-foreground text-sm">{truncate(n.body, 100)}</p>
        )}
        <div className="flex items-center gap-2">
          {url && canOpen(n) && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-2"
              onClick={() => {
                openNotification(n);
                acknowledge(n.id);
              }}
            >
              <ExternalLink className="mr-1 h-3.5 w-3.5" />
              Open
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            onClick={() => {
              setOpen(false);
              navigate("/inbox");
            }}
          >
            <Inbox className="mr-1 h-3.5 w-3.5" />
            Read in Inbox
          </Button>
        </div>
        <p className="text-muted-foreground text-xs">{formatDate(n.created_at)}</p>
      </div>
    );
  };

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="outline" size="icon" className="relative" aria-label="notifications">
          <Bell className="h-4 w-4" />
          {unread > 0 && (
            <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-destructive px-1 text-xs text-destructive-foreground">
              {unread}
            </span>
          )}
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="w-full overflow-y-auto sm:w-[440px] sm:max-w-none">
        <SheetHeader>
          <SheetTitle>Notifications</SheetTitle>
          <SheetDescription>Unread invitations, approvals and workspace activity</SheetDescription>
        </SheetHeader>
        <div className="mt-6 flex flex-col">
          {current.length > 0 && (
            <section className="flex flex-col gap-4">{current.map(renderItem)}</section>
          )}
          {others.size > 0 && (
            <div className="border-border mt-8 border-t pt-6">
              {[...others.entries()].map(([workspaceId, group]) => (
                <section key={workspaceId} className="mt-6 flex flex-col gap-4 first:mt-0">
                  <div className="flex items-center gap-3">
                    <h3 className="text-muted-foreground text-xs font-semibold tracking-widest uppercase">
                      {workspaceName(group[0])}
                    </h3>
                    <div className="border-border h-px flex-1" />
                  </div>
                  {group.map(renderItem)}
                </section>
              ))}
            </div>
          )}
          {items.length === 0 && (
            <p className="text-muted-foreground text-sm">No unread notifications.</p>
          )}
          <div className="border-border mt-8 border-t pt-4">
            <Button
              variant="outline"
              className="w-full"
              onClick={() => {
                setOpen(false);
                navigate("/inbox");
              }}
            >
              <Inbox className="mr-2 h-4 w-4" />
              Go to Inbox
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
