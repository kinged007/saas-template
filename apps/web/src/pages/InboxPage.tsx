import { useEffect, useMemo, useRef, useState } from "react";
import { useList, useUpdate, useCustomMutation, useCustom, useInvalidate, useGetIdentity } from "@refinedev/core";
import Markdown from "react-markdown";
import { ArrowLeft, Inbox, Mail, MailOpen, ExternalLink, SendHorizontal, Pencil, Archive, ArchiveRestore, Search, MessageSquare } from "lucide-react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { formatDate } from "../components/ui";
import { PageHeader } from "../components/refine-ui/layout/page-header";
import { cn } from "@/lib/utils";
import type { Notification, Conversation, Message, Identity } from "../types";
import { ComposeDialog } from "../components/inbox/ComposeDialog";
import { TiptapEditor } from "../components/inbox/TiptapEditor";

type Tab = "messages" | "notifications";
type StatusFilter = "unread" | "read" | "all";
type ArchivedFilter = "active" | "archived";

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
  const { data: identity } = useGetIdentity<Identity>();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTab = (searchParams.get("tab") as Tab) || "messages";
  const initialConvId = searchParams.get("conversationId") || null;
  const [tab, setTab] = useState<Tab>(initialTab === "notifications" ? "notifications" : "messages");
  const [selectedConvId, setSelectedConvId] = useState<string | null>(initialConvId);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("unread");
  const [archivedFilter, setArchivedFilter] = useState<ArchivedFilter>("active");
  const [searchInput, setSearchInput] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [composeOpen, setComposeOpen] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [editTitleValue, setEditTitleValue] = useState("");
  const [draft, setDraft] = useState("");
  const [, setDraftHtml] = useState("");
  const selectedRef = useRef<Notification | null>(null);
  const openedAtRef = useRef(0);
  const pendingTimerRef = useRef<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const invalidate = useInvalidate();

  // Debounce search
  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(searchInput.trim()), 300);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  // Sync tab to URL
  useEffect(() => {
    const params = new URLSearchParams(searchParams);
    params.set("tab", tab);
    if (selectedConvId) params.set("conversationId", selectedConvId);
    else params.delete("conversationId");
    setSearchParams(params, { replace: true });
  }, [tab, selectedConvId]);

  // Watch initial param changes (deep link from NotificationCenter)
  useEffect(() => {
    const pTab = searchParams.get("tab") as Tab | null;
    const pConv = searchParams.get("conversationId");
    if (pTab && pTab !== tab) setTab(pTab);
    if (pConv && pConv !== selectedConvId) setSelectedConvId(pConv);
  }, [searchParams]);

  // Notifications data (workspace-scoped)
  const { result: notifResult } = useList<Notification>({
    resource: "notifications",
    pagination: { pageSize: 200 },
    sorters: [{ field: "created_at", order: "desc" }],
    filters:
      statusFilter === "all"
        ? []
        : [{ field: "acknowledged", operator: "eq", value: statusFilter === "unread" ? "false" : "true" }],
    queryOptions: { enabled: tab === "notifications" },
  });
  const { mutate: updateNotif } = useUpdate();

  const allNotifications = notifResult?.data ?? [];

  // Conversations data
  const convFilters = useMemo(() => {
    const f: Array<{ field: string; operator: string; value: string }> = [];
    f.push({ field: "archived", operator: "eq", value: archivedFilter === "archived" ? "true" : "false" });
    if (debouncedQ) f.push({ field: "q", operator: "contains", value: debouncedQ });
    return f;
  }, [archivedFilter, debouncedQ]);

  const { result: convResult, query: convQuery } = useList<Conversation>({
    resource: "conversations",
    pagination: { pageSize: 20 },
    sorters: [{ field: "last_message_at", order: "desc" }],
    filters: convFilters as never,
    queryOptions: { enabled: tab === "messages" },
  });

  const conversations = (convResult?.data ?? []) as Conversation[];

  const selectedConversation = useMemo(() => {
    return conversations.find((c) => c.id === selectedConvId) ?? null;
  }, [conversations, selectedConvId]);

  const { mutate: updateConv } = useUpdate();
  const { mutate: customMutate } = useCustomMutation();
  const { mutateAsync: customMutateAsync } = useCustomMutation();

  // Messages for selected conversation
  const { result: messagesResult, query: messagesQuery } = useCustom<Message[]>({
    url: selectedConvId ? `conversations/${selectedConvId}/messages` : "",
    method: "get",
    config: {
      query: { limit: 100, sort: "created_at", order: "asc" },
    },
    queryOptions: {
      enabled: !!selectedConvId && tab === "messages",
    },
  });
  const messages: Message[] = useMemo(() => {
    const raw = messagesResult?.data as unknown;
    if (!raw) return [];
    if (Array.isArray(raw)) return raw as Message[];
    return [];
  }, [messagesResult]);
  const messagesLoading = (messagesQuery as unknown as { isLoading?: boolean })?.isLoading ?? false;
  const refetchMessages = () => messagesQuery.refetch();

  // Auto scroll to bottom when messages change
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  // Mark read when conversation opened
  useEffect(() => {
    if (!selectedConvId || tab !== "messages") return;
    // Don't mark if already read? But we mark anyway; backend is idempotent
    customMutate(
      {
        url: `conversations/${selectedConvId}/read`,
        method: "patch",
        values: {},
      },
      {
        onSuccess: () => {
          // Invalidate conversation list to update unread dot
          invalidate({ resource: "conversations", invalidates: ["list"] });
        },
      }
    );
  }, [selectedConvId]);

  // Notification helpers (old inbox behavior)
  const [selectedNotif, setSelectedNotif] = useState<Notification | null>(null);

  const markNotifRead = (id: string) =>
    updateNotif({
      resource: "notifications",
      id,
      values: { acknowledged: true },
      successNotification: false,
    });
  const markNotifUnread = (id: string) =>
    updateNotif({
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
      markNotifRead(id);
      pendingTimerRef.current = null;
    }, delay);
  };
  const exitCurrent = () => {
    const cur = selectedRef.current;
    if (cur && !cur.acknowledged) scheduleMarkRead(cur.id, openedAtRef.current);
    selectedRef.current = null;
  };
  const handleSelectNotif = (n: Notification) => {
    // If conversation_message, deep link to messages tab
    const payload = n.payload as Record<string, unknown> | undefined;
    const convId = payload?.conversation_id as string | undefined;
    if (n.type === "conversation_message" && convId) {
      setTab("messages");
      setSelectedConvId(convId);
      return;
    }
    if (n.id === selectedRef.current?.id) return;
    exitCurrent();
    openedAtRef.current = Date.now();
    selectedRef.current = n;
    setSelectedNotif(n);
  };
  const handleCloseNotif = () => {
    exitCurrent();
    setSelectedNotif(null);
  };
  useEffect(() => {
    return () => {
      const cur = selectedRef.current;
      if (cur && !cur.acknowledged) scheduleMarkRead(cur.id, openedAtRef.current);
    };
  }, []);
  const toggleAck = () => {
    const cur = selectedRef.current;
    if (!cur) return;
    const next = { ...cur, acknowledged: !cur.acknowledged };
    setSelectedNotif(next);
    if (next.acknowledged) markNotifRead(cur.id);
    else markNotifUnread(cur.id);
  };
  const linkUrl = (n: Notification) => (n.payload as Record<string, unknown> | undefined)?.url as string | undefined;

  // Conversation actions
  const handleSelectConv = (id: string) => {
    setSelectedConvId(id);
    // Trigger refetch
    setTimeout(() => refetchMessages(), 0);
  };

  const handleSend = async () => {
    if (!selectedConvId || !draft.trim()) return;
    try {
      await customMutateAsync({
        url: `conversations/${selectedConvId}/messages`,
        method: "post",
        values: { body: draft },
        successNotification: false,
        errorNotification: false,
      });
      setDraft("");
      setDraftHtml("");
      // Refetch messages and conv list
      refetchMessages();
      convQuery.refetch();
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message || String(err);
      toast.error(msg);
    }
  };

  const handleArchive = (archived: boolean) => {
    if (!selectedConvId) return;
    customMutate(
      {
        url: `conversations/${selectedConvId}/archive`,
        method: "patch",
        values: { archived },
        successNotification: false,
        errorNotification: false,
      },
      {
        onSuccess: () => {
          convQuery.refetch();
        },
      }
    );
  };

  const handleTitleSave = () => {
    if (!selectedConvId || !editTitleValue.trim()) return;
    updateConv(
      {
        resource: "conversations",
        id: selectedConvId,
        values: { title: editTitleValue.trim() },
        successNotification: false,
        errorNotification: false,
      },
      {
        onSuccess: () => {
          setEditingTitle(false);
          convQuery.refetch();
        },
        onError: (e) => {
          toast.error(String((e as { message?: string })?.message ?? e));
        },
      }
    );
  };

  // Sync editTitleValue when conversation changes
  useEffect(() => {
    if (selectedConversation) {
      setEditTitleValue(selectedConversation.title ?? "");
    }
  }, [selectedConversation?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <PageHeader
        title="Inbox"
        actions={
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border p-1">
              <Button
                variant={tab === "messages" ? "secondary" : "ghost"}
                size="sm"
                className="h-7"
                onClick={() => setTab("messages")}
              >
                <MessageSquare className="mr-1 h-3.5 w-3.5" />
                Messages
              </Button>
              <Button
                variant={tab === "notifications" ? "secondary" : "ghost"}
                size="sm"
                className="h-7"
                onClick={() => setTab("notifications")}
              >
                <Mail className="mr-1 h-3.5 w-3.5" />
                Notifications
              </Button>
            </div>
            {tab === "messages" && (
              <Button size="sm" onClick={() => setComposeOpen(true)}>
                Compose
              </Button>
            )}
            {tab === "notifications" && (
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
            )}
          </div>
        }
      />

      {tab === "messages" ? (
        <div className="flex min-h-0 flex-1 overflow-hidden rounded-lg border">
          {/* Left pane */}
          <div className={cn("flex w-full flex-col border-r md:w-80", selectedConvId ? "hidden md:flex" : "flex")}>
            <div className="flex items-center gap-2 border-b p-3">
              <div className="relative flex-1">
                <Search className="text-muted-foreground absolute left-2 top-2.5 h-4 w-4" />
                <Input
                  placeholder="Search title or preview…"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  className="pl-8"
                />
              </div>
              <Select value={archivedFilter} onValueChange={(v) => setArchivedFilter(v as ArchivedFilter)}>
                <SelectTrigger className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="archived">Archived</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1 overflow-y-auto">
              {conversations.map((c) => {
                const isActive = c.id === selectedConvId;
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => handleSelectConv(c.id)}
                    className={cn(
                      "flex w-full flex-col gap-1 border-b px-4 py-3 text-left transition-colors",
                      isActive ? "bg-accent" : "hover:bg-accent/50"
                    )}
                  >
                    <div className="flex items-center gap-2">
                      {c.unread_count > 0 && <span className="bg-primary mt-1 h-2 w-2 shrink-0 rounded-full" />}
                      <p className={cn("min-w-0 flex-1 truncate text-sm", c.unread_count > 0 ? "font-semibold" : "font-medium")}>
                        {c.title || "Untitled"}
                      </p>
                      {c.unread_count > 0 && (
                        <Badge variant="default" className="h-5 px-1.5 text-xs">
                          {c.unread_count}
                        </Badge>
                      )}
                    </div>
                    <p className="text-muted-foreground line-clamp-1 pl-4 text-xs">{truncate(c.last_message_preview ?? "", 80)}</p>
                    <div className="flex items-center gap-2 pl-4">
                      <div className="flex -space-x-1">
                        {c.participants.slice(0, 3).map((p) => (
                          <Avatar key={p.id} className="h-5 w-5 border-2 border-background">
                            <AvatarImage src={p.avatar_url ?? undefined} />
                            <AvatarFallback className="text-[9px]">{p.display_name.slice(0, 2).toUpperCase()}</AvatarFallback>
                          </Avatar>
                        ))}
                        {c.participants.length > 3 && (
                          <span className="text-muted-foreground bg-muted flex h-5 w-5 items-center justify-center rounded-full border-2 border-background text-[10px]">
                            +{c.participants.length - 3}
                          </span>
                        )}
                      </div>
                      <span className="text-muted-foreground truncate text-[11px]">{c.participants.map((p) => p.display_name).join(", ")}</span>
                    </div>
                    <p className="text-muted-foreground pl-4 text-[11px]">{formatDate(c.last_message_at)}</p>
                  </button>
                );
              })}
              {conversations.length === 0 && (
                <div className="flex flex-1 items-center justify-center p-6">
                  <p className="text-muted-foreground text-sm">
                    {archivedFilter === "archived" ? "No archived conversations." : "No conversations yet."}
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Right pane */}
          <div className={cn("flex min-w-0 flex-1 flex-col overflow-hidden", selectedConvId ? "flex" : "hidden md:flex")}>
            {selectedConversation ? (
              <div className="flex min-h-0 flex-1 flex-col">
                {/* Thread header */}
                <div className="flex flex-col gap-3 border-b p-4">
                  <div className="flex items-center gap-2 md:hidden">
                    <Button size="sm" variant="ghost" onClick={() => setSelectedConvId(null)}>
                      <ArrowLeft className="mr-1 h-4 w-4" />
                      Back
                    </Button>
                  </div>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      {editingTitle ? (
                        <div className="flex items-center gap-2">
                          <Input
                            value={editTitleValue}
                            onChange={(e) => setEditTitleValue(e.target.value)}
                            className="h-8"
                            placeholder="Conversation title"
                            autoFocus
                          />
                          <Button size="sm" onClick={handleTitleSave}>
                            Save
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setEditingTitle(false)}>
                            Cancel
                          </Button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <h3 className="truncate text-lg font-semibold">{selectedConversation.title || "Untitled"}</h3>
                          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setEditingTitle(true)}>
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      )}
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        {selectedConversation.participants.map((p) => (
                          <Badge key={p.id} variant="secondary" className="gap-1">
                            <Avatar className="h-4 w-4">
                              <AvatarImage src={p.avatar_url ?? undefined} />
                              <AvatarFallback className="text-[8px]">{p.display_name.slice(0, 2).toUpperCase()}</AvatarFallback>
                            </Avatar>
                            {p.display_name}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleArchive(!selectedConversation.is_archived)}
                      title={selectedConversation.is_archived ? "Unarchive (only for you)" : "Archive (only for you)"}
                    >
                      {selectedConversation.is_archived ? (
                        <>
                          <ArchiveRestore className="mr-1 h-3.5 w-3.5" />
                          Unarchive
                        </>
                      ) : (
                        <>
                          <Archive className="mr-1 h-3.5 w-3.5" />
                          Archive
                        </>
                      )}
                    </Button>
                  </div>
                </div>

                {/* Messages */}
                <div className="flex-1 overflow-y-auto p-4">
                  <div className="flex flex-col gap-4">
                    {messagesLoading ? (
                      <p className="text-muted-foreground text-sm">Loading…</p>
                    ) : messages.length === 0 ? (
                      <p className="text-muted-foreground text-sm">No messages yet.</p>
                    ) : (
                      messages.map((m) => {
                        const isSelf = identity?.id === m.sender_id;
                        return (
                          <div key={m.id} className={cn("flex gap-3", isSelf ? "justify-end" : "justify-start")}>
                            {!isSelf && (
                              <Avatar className="h-7 w-7 shrink-0">
                                <AvatarImage src={m.sender_avatar_url ?? undefined} />
                                <AvatarFallback className="text-xs">{m.sender_name.slice(0, 2).toUpperCase()}</AvatarFallback>
                              </Avatar>
                            )}
                            <div className={cn("max-w-[75%] rounded-lg px-3 py-2", isSelf ? "bg-primary text-primary-foreground" : "bg-muted")}>
                              {!isSelf && <p className="mb-1 text-xs font-medium opacity-70">{m.sender_name}</p>}
                              <div className={cn("prose prose-sm dark:prose-invert max-w-none break-words", isSelf ? "prose-invert" : "")}>
                                <Markdown>{m.body}</Markdown>
                              </div>
                              <p className={cn("mt-1 text-[11px]", isSelf ? "text-primary-foreground/70" : "text-muted-foreground")}>
                                {formatDate(m.created_at)}
                              </p>
                            </div>
                            {isSelf && (
                              <Avatar className="h-7 w-7 shrink-0">
                                <AvatarImage src={m.sender_avatar_url ?? undefined} />
                                <AvatarFallback className="text-xs">{m.sender_name.slice(0, 2).toUpperCase()}</AvatarFallback>
                              </Avatar>
                            )}
                          </div>
                        );
                      })
                    )}
                    <div ref={messagesEndRef} />
                  </div>
                </div>

                {/* Composer */}
                <div className="border-t p-3">
                  <div className="flex flex-col gap-2">
                    <TiptapEditor
                      value={draft}
                      onChange={(md, html) => {
                        setDraft(md);
                        setDraftHtml(html);
                      }}
                      placeholder="Write a message… (markdown supported)"
                      minHeight="60px"
                    />
                    <div className="flex justify-end">
                      <Button size="sm" onClick={handleSend} disabled={!draft.trim()}>
                        <SendHorizontal className="mr-1 h-3.5 w-3.5" />
                        Send
                      </Button>
                    </div>
                  </div>
                  <p className="text-muted-foreground mt-2 text-xs">Press the toolbar to format. Stored as markdown, rendered with react-markdown.</p>
                </div>
              </div>
            ) : (
              <div className="flex flex-1 items-center justify-center">
                <div className="text-center">
                  <MessageSquare className="text-muted-foreground/40 mx-auto h-12 w-12" />
                  <p className="text-muted-foreground mt-3 text-sm">Select a conversation to read</p>
                  <Button variant="outline" size="sm" className="mt-3" onClick={() => setComposeOpen(true)}>
                    New conversation
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        /* Notifications tab - simplified workspace-scoped list */
        <div className="flex min-h-0 flex-1 overflow-hidden rounded-lg border">
          <div className={cn("flex w-full flex-col overflow-y-auto border-r md:w-80", selectedNotif ? "hidden md:flex" : "flex")}>
            {allNotifications.map((n) => {
              const isActive = n.id === selectedNotif?.id;
              const isConvMsg = n.type === "conversation_message";
              return (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => handleSelectNotif(n)}
                  className={cn(
                    "flex flex-col gap-1 border-b px-4 py-3 text-left transition-colors",
                    isActive ? "bg-accent" : "hover:bg-accent/50"
                  )}
                >
                  <div className="flex items-center gap-2">
                    {!n.acknowledged && <span className="bg-primary mt-1 h-2 w-2 shrink-0 rounded-full" />}
                    <p className={cn("min-w-0 flex-1 truncate text-sm", !n.acknowledged ? "font-semibold" : "font-medium")}>
                      {n.title}
                    </p>
                    {isConvMsg && <Badge variant="outline" className="shrink-0 text-[10px]">message</Badge>}
                  </div>
                  <p className="text-muted-foreground line-clamp-1 pl-4 text-xs">{truncate(n.body, 100)}</p>
                  <p className="text-muted-foreground pl-4 text-[11px]">{formatDate(n.created_at)}</p>
                </button>
              );
            })}
            {allNotifications.length === 0 && (
              <div className="flex flex-1 items-center justify-center p-6">
                <p className="text-muted-foreground text-sm">No notifications.</p>
              </div>
            )}
          </div>

          <div className={cn("flex min-w-0 flex-1 flex-col overflow-y-auto", selectedNotif ? "flex" : "hidden md:flex")}>
            {selectedNotif ? (
              <div className="flex flex-1 flex-col p-6">
                <div className="mb-4 flex items-center gap-3 md:hidden">
                  <Button size="sm" variant="ghost" onClick={handleCloseNotif}>
                    <ArrowLeft className="mr-1 h-4 w-4" />
                    Back
                  </Button>
                </div>
                <div className="mb-6 flex flex-col gap-2">
                  <h3 className="text-xl font-semibold">{selectedNotif.title}</h3>
                  <div className="text-muted-foreground flex flex-wrap items-center gap-3 text-sm">
                    <span>{formatDate(selectedNotif.created_at)}</span>
                    {selectedNotif.workspace_name && (
                      <>
                        <span>·</span>
                        <Badge variant="secondary">{selectedNotif.workspace_name}</Badge>
                      </>
                    )}
                    {selectedNotif.type === "conversation_message" && <Badge variant="outline">message</Badge>}
                  </div>
                </div>
                <div className="prose prose-sm dark:prose-invert max-w-none flex-1">
                  <Markdown>{selectedNotif.body || ""}</Markdown>
                </div>
                <div className="border-border mt-6 flex items-center gap-2 border-t pt-4">
                  {linkUrl(selectedNotif) && (
                    <Button size="sm" variant="outline" asChild>
                      <a href={linkUrl(selectedNotif)} target="_blank" rel="noopener noreferrer">
                        <ExternalLink className="mr-1 h-3.5 w-3.5" />
                        Open link
                      </a>
                    </Button>
                  )}
                  {selectedNotif.type === "conversation_message" && Boolean((selectedNotif.payload as Record<string, unknown>)?.conversation_id) && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        const convId = (selectedNotif.payload as Record<string, unknown>).conversation_id as string;
                        setTab("messages");
                        setSelectedConvId(convId);
                      }}
                    >
                      <MessageSquare className="mr-1 h-3.5 w-3.5" />
                      Open conversation
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={toggleAck}>
                    {selectedNotif.acknowledged ? (
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
                  <p className="text-muted-foreground mt-3 text-sm">Select a notification to read</p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <ComposeDialog
        open={composeOpen}
        onOpenChange={setComposeOpen}
        onCreated={(conv) => {
          setSelectedConvId(conv.id);
          setTab("messages");
          convQuery.refetch();
        }}
      />
    </div>
  );
}
