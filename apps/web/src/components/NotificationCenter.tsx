import { useEffect, useMemo, useRef, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Bell, ExternalLink, Inbox, MessageSquare } from "lucide-react";
import { useList, useUpdate, useCustom } from "@refinedev/core";
import { useNavigate } from "react-router";

import type { Notification } from "../types";
import { formatDate } from "./ui";
import { stripMarkdown, truncate } from "@/lib/markdown";
import { liveChannels, subscribeLive } from "../providers/liveProvider";

function truncateEscaped(text: string | undefined, max: number): string {
  return truncate(stripMarkdown(text), max);
}

export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const { result, query } = useList<Notification>({
    resource: "notifications",
    pagination: { pageSize: 100 },
    sorters: [{ field: "created_at", order: "desc" }],
    filters: [{ field: "acknowledged", operator: "eq", value: "false" }],
  });
  const { mutate } = useUpdate();
  const navigate = useNavigate();

  const rawItems = result?.data ?? [];
  // Group conversation_message pointers by conversation_id – show only the latest per conversation
  const items = useMemo(() => {
    const map = new Map<string, Notification>();
    const others: Notification[] = [];
    for (const n of rawItems as Notification[]) {
      if (n.type === "conversation_message") {
        const cid = (n.payload as Record<string, unknown> | undefined)?.conversation_id as string | undefined;
        if (!cid) {
          others.push(n);
          continue;
        }
        const existing = map.get(cid);
        if (!existing || (n.created_at ?? "") > (existing.created_at ?? "")) {
          map.set(cid, n);
        }
      } else {
        others.push(n);
      }
    }
    const grouped = Array.from(map.values());
    const merged = [...others, ...grouped].sort((a, b) =>
      (b.created_at ?? "").localeCompare(a.created_at ?? "")
    );
    return merged;
  }, [rawItems]);

  const { result: notifUnreadResult, query: notifUnreadQuery } = useCustom<{ count: number }>({
    url: "notifications/unread-count",
    method: "get",
  });
  const { result: convUnreadResult, query: convUnreadQuery } = useCustom<{ count: number; unread_conversations: number }>({
    url: "conversations/unread-count",
    method: "get",
  });

  const notifCount = (notifUnreadResult?.data as { count?: number } | undefined)?.count ?? (result?.total ?? items.length);
  // Badge counts total unread conversation MESSAGES (not just conversations)
  // so every incoming message ticks the bell instantly.
  const convUnreadMessages = (convUnreadResult?.data as { count?: number } | undefined)?.count ?? 0;
  // Combined badge: notifications + unread conversation messages
  const unread = notifCount + convUnreadMessages;

  useEffect(() => {
    if (open) {
      query.refetch();
      notifUnreadQuery.refetch();
      convUnreadQuery.refetch();
    }
  }, [open, query, notifUnreadQuery, convUnreadQuery]);

  // Realtime: cache patches in liveCache keep the badge and list fresh with
  // zero requests. This subscription keeps the socket alive and only
  // reconciles the open sheet as a fallback (covers missed frames).
  const openRef = useRef(open);
  openRef.current = open;
  useEffect(() => {
    const refetchWhenOpen = () => {
      if (openRef.current) query.refetch();
    };
    const unsubscribers = [
      subscribeLive(liveChannels.notifications, refetchWhenOpen),
      subscribeLive(liveChannels.conversations, refetchWhenOpen),
    ];
    return () => unsubscribers.forEach((unsubscribe) => unsubscribe());
  }, [query]);

  const acknowledge = (id: string) => {
    mutate(
      { resource: "notifications", id, values: { acknowledged: true } },
      { onSuccess: () => { query.refetch(); notifUnreadQuery.refetch(); } },
    );
  };

  const linkUrl = (n: Notification) =>
    (n.payload as Record<string, unknown> | undefined)?.url as string | undefined;

  const openNotification = (n: Notification) => {
    const url = linkUrl(n);
    if (!url) return;
    setOpen(false);
    navigate(url);
  };

  const openConversation = (n: Notification) => {
    const convId = (n.payload as Record<string, unknown> | undefined)?.conversation_id as string | undefined;
    if (!convId) return;
    setOpen(false);
    navigate(`/inbox?tab=messages&conversationId=${convId}`);
    // Acknowledge all unread pointers for this conversation (grouped view)
    const toAck = (rawItems as Notification[]).filter(
      (x) =>
        x.type === "conversation_message" &&
        (x.payload as Record<string, unknown> | undefined)?.conversation_id === convId &&
        !x.acknowledged
    );
    if (toAck.length > 0) {
      for (const item of toAck) acknowledge(item.id);
    } else {
      acknowledge(n.id);
    }
  };

  const renderItem = (n: Notification) => {
    const url = linkUrl(n);
    const isMessage = n.type === "conversation_message";
    const payload = n.payload as Record<string, unknown> | undefined;
    const senderName = payload?.sender_name as string | undefined;

    return (
      <div key={n.id} className="border-border flex flex-col gap-2 rounded-lg border p-3">
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold flex-1 truncate">{n.title}</p>
          {isMessage && <Badge variant="outline" className="shrink-0 text-[10px]">message</Badge>}
        </div>
        {isMessage && senderName && (
          <p className="text-muted-foreground text-xs">From {senderName}</p>
        )}
        {n.body && (
          <p className="text-muted-foreground text-sm">{truncateEscaped(n.body, 100)}</p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {isMessage ? (
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-2"
              onClick={() => openConversation(n)}
            >
              <MessageSquare className="mr-1 h-3.5 w-3.5" />
              Open conversation
            </Button>
          ) : (
            url && (
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
            )
          )}
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            onClick={() => {
              if (isMessage) {
                const convId = payload?.conversation_id as string | undefined;
                if (convId) {
                  setOpen(false);
                  navigate(`/inbox?tab=messages&conversationId=${convId}`);
                  const toAck = (rawItems as Notification[]).filter(
                    (x) =>
                      x.type === "conversation_message" &&
                      (x.payload as Record<string, unknown> | undefined)?.conversation_id === convId &&
                      !x.acknowledged
                  );
                  for (const item of toAck) acknowledge(item.id);
                } else {
                  setOpen(false);
                  navigate("/inbox?tab=messages");
                }
              } else {
                setOpen(false);
                navigate("/inbox?tab=notifications");
              }
            }}
          >
            <Inbox className="mr-1 h-3.5 w-3.5" />
            {isMessage ? "In Messages" : "In Inbox"}
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
          <SheetDescription>Unread invitations, messages and workspace activity</SheetDescription>
        </SheetHeader>
        <div className="mt-6 flex flex-col gap-4">
          {items.length > 0 ? (
            <section className="flex flex-col gap-4">{items.map(renderItem)}</section>
          ) : (
            <p className="text-muted-foreground text-sm">No unread notifications.</p>
          )}
          <div className="border-border mt-8 border-t pt-4">
            <Button
              variant="outline"
              className="w-full"
              onClick={() => {
                setOpen(false);
                navigate("/inbox?tab=notifications");
              }}
            >
              <Inbox className="mr-2 h-4 w-4" />
              See all Notifications
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
