import { useEffect, useMemo, useRef, useState } from "react";
import { useUpdate, useCustomMutation, useInvalidate, useGetIdentity } from "@refinedev/core";
import { useWorkspaceList, useWorkspaceCustom } from "../hooks/useWorkspaceQuery";
import Markdown from "react-markdown";
import { ArrowLeft, Inbox, Mail, MailOpen, ExternalLink, SendHorizontal, Pencil, Archive, ArchiveRestore, Search, MessageSquare, PanelLeftClose, PanelLeftOpen, X, Check, UserPlus } from "lucide-react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";
import { markdownComponents, markdownComponentsInverted, stripMarkdown, truncate as truncatePreview } from "@/lib/markdown";
import { mentionRemarkPlugin, mentionUrlTransform, type MentionTarget } from "@/lib/mentions";
import { notificationLinkUrl } from "@/lib/notificationLink";
import { errorMessage } from "@/utils/errorMessage";
import { activeWorkspacePermissions } from "../utils/permissions";
import { isClientError } from "../providers/queryClient";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { UserAvatar } from "@/components/ui/user-avatar";
import { UserProfileDialog } from "@/components/UserProfileDialog";
import { formatDate } from "../components/ui";
import { TabbedPageHeader } from "../components/refine-ui/layout/tabbed-page-header";
import { cn } from "@/lib/utils";
import type { Notification, Conversation, Message, Identity, Member } from "../types";
import { getDisplayName, getParticipantDisplayName, getMemberDisplayName } from "../types";
import { ComposeDialog } from "../components/inbox/ComposeDialog";
import { TiptapEditor } from "../components/inbox/TiptapEditor";
import { EditParticipantsDialog } from "../components/inbox/EditParticipantsDialog";
import {
  applyConversationRead,
  applyMessageCreated,
  invalidateUnreadCounts,
  removeThreadMessage,
  upsertThreadMessage,
} from "../providers/liveCache";

type Tab = "messages" | "notifications";
type StatusFilter = "unread" | "read" | "all";
type ArchivedFilter = "active" | "archived";

const STATUS_OPTIONS: Array<{ value: StatusFilter; label: string }> = [
  { value: "unread", label: "Unread" },
  { value: "read", label: "Read" },
  { value: "all", label: "All" },
];

function formatListTime(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toDateString() === new Date().toDateString()
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString();
}

function truncateEscaped(text: string | undefined | null, max: number): string {
  return truncatePreview(stripMarkdown(text ?? undefined), max);
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
  const [mentionIds, setMentionIds] = useState<string[]>([]);
  const [editParticipantsOpen, setEditParticipantsOpen] = useState(false);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [searchExpanded, setSearchExpanded] = useState(false);
  const searchContainerRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [confirmArchiveId, setConfirmArchiveId] = useState<string | null>(null);
  const [selectedUser, setSelectedUser] = useState<
    | { userId: string; fallback: { display_name?: string; email?: string | null; avatar_url?: string | null } }
    | null
  >(null);
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

  // Search expand: Esc or click outside collapses (keeps text), focus when expanded
  useEffect(() => {
    if (!searchExpanded) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (searchContainerRef.current && !searchContainerRef.current.contains(target)) {
        setSearchExpanded(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSearchExpanded(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey as unknown as EventListener);
    window.setTimeout(() => searchInputRef.current?.focus(), 0);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey as unknown as EventListener);
    };
  }, [searchExpanded]);

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

  // When left panel collapses, close expanded search (keeps text)
  useEffect(() => {
    if (leftCollapsed) setSearchExpanded(false);
  }, [leftCollapsed]);

  // Clear archive confirmation when switching tabs/filters
  useEffect(() => {
    setConfirmArchiveId(null);
  }, [archivedFilter, tab]);

  // Notifications data (workspace-scoped) – hide conversation_message pointers; they are surfaced via Messages tab + right sidebar grouped
  const { result: notifResult, query: notifListQuery } = useWorkspaceList<Notification>({
    resource: "notifications",
    pagination: { pageSize: 200 },
    sorters: [{ field: "created_at", order: "desc" }],
    filters: [
      ...(statusFilter === "all"
        ? []
        : [{ field: "acknowledged", operator: "eq", value: statusFilter === "unread" ? "false" : "true" } as const]),
      { field: "type", operator: "ne", value: "conversation_message" } as const,
    ] as never,
    queryOptions: { enabled: tab === "notifications" },
  });
  const allNotifications = useMemo(() => {
    const data = (notifResult?.data ?? []) as Notification[];
    return data.filter((n) => n.type !== "conversation_message");
  }, [notifResult?.data]);

  const { mutate: updateNotif } = useUpdate();
  const { mutate: markAllNotif, mutation: markAllMutation } = useCustomMutation();
  const markingAll = markAllMutation.isPending;
  const unreadCount = allNotifications.filter((n) => !n.acknowledged).length;

  const markAllRead = () => {
    markAllNotif(
      {
        url: "notifications/read-all",
        method: "patch",
        values: {},
        successNotification: (res) => {
          const count = (res as unknown as { data?: { acknowledged?: number } })?.data?.acknowledged ?? 0;
          return {
            message: count > 0 ? `${count} notification${count > 1 ? "s" : ""} marked as read` : "No unread notifications",
            type: "success",
          };
        },
      },
      {
        onSuccess: () => {
          notifListQuery.refetch();
          selectedRef.current = null;
          setSelectedNotif(null);
        },
      }
    );
  };

  // Conversations data
  const convFilters = useMemo(() => {
    const f: Array<{ field: string; operator: string; value: string }> = [];
    f.push({ field: "archived", operator: "eq", value: archivedFilter === "archived" ? "true" : "false" });
    if (debouncedQ) f.push({ field: "q", operator: "contains", value: debouncedQ });
    return f;
  }, [archivedFilter, debouncedQ]);

  const { result: convResult, query: convQuery } = useWorkspaceList<Conversation>({
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

  const canManageParticipants = useMemo(() => {
    const perms = activeWorkspacePermissions(identity);
    return perms.includes("*") || perms.includes("message:update");
  }, [identity]);

  // Mentionable people, read straight from the active workspace's members.
  // This array is the container the `@` picker iterates.
  const { result: membersResult } = useWorkspaceList<Member>({
    resource: "members",
    pagination: { pageSize: 100 },
    queryOptions: { enabled: tab === "messages" && !!selectedConvId },
  });
  const mentionTargets: MentionTarget[] = useMemo(
    () =>
      (membersResult?.data ?? []).map((m) => ({
        id: m.id,
        type: "user",
        label: getMemberDisplayName(m),
        email: m.email,
        avatar_url: m.avatar_url,
        first_name: m.first_name,
        last_name: m.last_name,
        role: m.role,
      })),
    [membersResult],
  );

  // Names of the people in the open conversation, for mention highlighting.
  const participantNames = useMemo(
    () =>
      (selectedConversation?.participants ?? []).map((p) =>
        getParticipantDisplayName(
          p as unknown as { display_name: string; first_name?: string | null; last_name?: string | null },
        ),
      ),
    [selectedConversation],
  );

  // Built once per participant list, not once per message bubble.
  const mentionPlugins = useMemo(() => [mentionRemarkPlugin(participantNames)], [participantNames]);

  const { mutate: updateConv } = useUpdate();
  const { mutate: customMutate } = useCustomMutation();
  const { mutateAsync: customMutateAsync } = useCustomMutation();

  // Messages for selected conversation
  const { result: messagesResult, query: messagesQuery } = useWorkspaceCustom<Message[]>({
    url: selectedConvId ? `conversations/${selectedConvId}/messages` : "",
    method: "get",
    config: {
      query: { limit: 100 },
    },
    // The inline note in the thread header is this failure's only signal;
    // refine's default toast would echo it transiently next to the note.
    errorNotification: false,
    queryOptions: {
      enabled: !!selectedConvId && tab === "messages",
      // Network failures make one attempt; a 4xx never retries anyway.
      retry: false,
    },
  });
  const messages: Message[] = useMemo(() => {
    const raw = messagesResult?.data as unknown;
    if (raw && Array.isArray(raw)) return raw as Message[];
    return [];
  }, [messagesResult]);
  const messagesLoading = messagesQuery.isLoading;
  const messagesError = messagesQuery.isError;
  // A 4xx means the server answered and refused; only a transport failure or 5xx
  // leaves the cached list merely behind.
  const messagesRefused = messagesError && isClientError(messagesQuery.error);
  const hasCachedMessages = messages.length > 0;
  const staleNote = messagesError && hasCachedMessages;

  // Auto scroll to bottom when messages change; `messagesError` re-clamps when the
  // header note shrinks the pane and would otherwise clip the newest message.
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, messagesError]);

  // Mark read when conversation opened – also clears the grouped notification pointer for that conversation
  useEffect(() => {
    if (!selectedConvId || tab !== "messages") return;
    const conversationId = selectedConvId;
    customMutate(
      {
        url: `conversations/${conversationId}/read`,
        method: "patch",
        values: {},
      },
      {
        onSuccess: () => {
          applyConversationRead(conversationId);
        },
      }
    );
  }, [selectedConvId]); // eslint-disable-line react-hooks/exhaustive-deps

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

  // Conversation actions
  const handleSelectConv = (id: string) => {
    // Switching (or re-clicking) a conversation loads the thread via the
    // messages query key and marks it read — this also clears any unread
    // that accumulated from messages arriving while the thread was open.
    setSelectedConvId(id);
    customMutate(
      {
        url: `conversations/${id}/read`,
        method: "patch",
        values: {},
        successNotification: false,
        errorNotification: false,
      },
      {
        onSuccess: () => {
          applyConversationRead(id);
        },
      }
    );
  };

  const handleSend = async () => {
    if (!selectedConvId || !draft.trim()) return;
    const body = draft.trim();
    const conversationId = selectedConvId;
    const mentioned = mentionIds;
    // Optimistic: append directly to the thread cache so the message shows
    // before the server round-trip.
    const tempId = `optimistic-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const optimistic: Message = {
      id: tempId,
      conversation_id: conversationId,
      sender_type: "user",
      sender_id: identity?.id ?? "me",
      sender_name: getDisplayName(identity as Identity | null) || "You",
      sender_avatar_url: identity?.avatar_url ?? null,
      sender_email: identity?.email ?? null,
      body,
      body_html: null,
      created_at: new Date().toISOString(),
    };
    upsertThreadMessage(conversationId, optimistic);
    setDraft("");
    setDraftHtml("");
    setMentionIds([]);
    try {
      const res = await customMutateAsync({
        url: `conversations/${conversationId}/messages`,
        method: "post",
        values: { body, mentioned_user_ids: mentioned },
        successNotification: false,
        errorNotification: false,
      });
      const serverMsg = (res as unknown as { data?: Message })?.data as Message | undefined;
      removeThreadMessage(conversationId, tempId);
      if (serverMsg?.id) {
        // Reuse the realtime patch: appends the persisted message, bumps the
        // conversation preview, skips unread (own message).
        applyMessageCreated({
          conversation_id: serverMsg.conversation_id,
          message_id: serverMsg.id,
          sender_id: serverMsg.sender_id,
          sender_type: serverMsg.sender_type,
          sender_name: serverMsg.sender_name,
          sender_avatar_url: serverMsg.sender_avatar_url,
          sender_email: serverMsg.sender_email,
          body: serverMsg.body,
          body_preview: truncatePreview(stripMarkdown(serverMsg.body), 200),
          created_at: serverMsg.created_at,
        });
      }
      // Sending marks the conversation read server-side — reflect it locally.
      applyConversationRead(conversationId);
      // Mentioned users are joined server-side; the header list is now stale.
      if (mentioned.length > 0) convQuery.refetch();
    } catch (err: unknown) {
      removeThreadMessage(conversationId, tempId);
      const msg = (err as { message?: string })?.message || String(err);
      toast.error(msg);
      // Restore draft on failure for retry
      setDraft(body);
    }
  };

  const handleArchiveConversation = (conversationId: string, archived: boolean) => {
    customMutate(
      {
        url: `conversations/${conversationId}/archive`,
        method: "patch",
        values: { archived },
        successNotification: false,
        errorNotification: false,
      },
      {
        onSuccess: () => {
          setConfirmArchiveId(null);
          convQuery.refetch();
          invalidate({ resource: "conversations", invalidates: ["list"] });
          if (selectedConvId === conversationId && archived) {
            // If we archived the open thread, keep it selected but it will disappear from active list; allow user to see archived tab
          }
        },
        onError: (e) => {
          toast.error(errorMessage(e));
        },
      }
    );
  };

  const handleToggleRead = (conv: Conversation) => {
    const isUnread = conv.unread_count > 0;
    const url = isUnread ? `conversations/${conv.id}/read` : `conversations/${conv.id}/unread`;
    customMutate(
      {
        url,
        method: "patch",
        values: {},
        successNotification: false,
        errorNotification: false,
      },
      {
        onSuccess: () => {
          if (isUnread) {
            applyConversationRead(conv.id);
          } else {
            // Marking unread does not touch the row badge optimistically — the
            // refetched list carries the new count — but the sidebar badge and
            // the bell still need their counters refetched.
            invalidateUnreadCounts();
          }
          convQuery.refetch();
          invalidate({ resource: "conversations", invalidates: ["list"] });
          invalidate({ resource: "notifications", invalidates: ["list"] });
        },
        onError: (e) => {
          toast.error(errorMessage(e));
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
          toast.error(errorMessage(e));
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
    <div className="page-flush flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <TabbedPageHeader
        title="Inbox"
        tabs={
          <div className="flex w-full items-center gap-2 sm:w-auto">
            {tab === "messages" && (
              <Button size="sm" onClick={() => setComposeOpen(true)}>
                Compose
              </Button>
            )}
            <div className="flex flex-1 rounded-lg border p-1 sm:flex-none">
              <Button
                variant={tab === "messages" ? "secondary" : "ghost"}
                size="sm"
                className="h-7 flex-1 justify-center sm:flex-none"
                onClick={() => setTab("messages")}
              >
                <MessageSquare className="mr-1 h-3.5 w-3.5" />
                Messages
              </Button>
              <Button
                variant={tab === "notifications" ? "secondary" : "ghost"}
                size="sm"
                className="h-7 flex-1 justify-center sm:flex-none"
                onClick={() => setTab("notifications")}
              >
                <Mail className="mr-1 h-3.5 w-3.5" />
                Notifications
              </Button>
            </div>
          </div>
        }
      />

      {tab === "messages" ? (
        <div className="flex min-h-0 flex-1 overflow-hidden rounded-lg border">
          {/* Left pane */}
          <div
            className={cn(
              "flex w-full flex-col border-r transition-all duration-200",
              selectedConvId ? "hidden md:flex" : "flex",
              leftCollapsed ? "md:hidden" : "md:w-80 md:flex"
            )}
          >
            <div ref={searchContainerRef} className="flex items-center gap-2 border-b p-3">
              {searchExpanded ? (
                <div className="relative flex flex-1 items-center">
                  <Search className="text-muted-foreground pointer-events-none absolute left-2 top-2.5 h-4 w-4" />
                  <Input
                    ref={searchInputRef}
                    placeholder="Search title or preview…"
                    value={searchInput}
                    onChange={(e) => setSearchInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Escape") setSearchExpanded(false);
                    }}
                    className={cn("pl-8 pr-8", searchInput.trim() && "border-ring ring-1 ring-ring")}
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    className="absolute right-1 top-1 h-7 w-7 shrink-0"
                    onClick={() => {
                      setSearchInput("");
                      // keep search bar expanded so user can type a new query; Esc / outside click still collapses
                      searchInputRef.current?.focus();
                    }}
                    aria-label="Clear search"
                    title="Clear search"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ) : (
                <>
                  <Button
                    variant={searchInput.trim() ? "secondary" : "ghost"}
                    size="icon"
                    onClick={() => setSearchExpanded(true)}
                    aria-label="Search"
                    title="Search"
                    className={cn("h-9 w-9 shrink-0", searchInput.trim() && "ring-1 ring-ring border-ring")}
                  >
                    <Search className="h-4 w-4" />
                  </Button>
                  <Select value={archivedFilter} onValueChange={(v) => setArchivedFilter(v as ArchivedFilter)}>
                    <SelectTrigger className="w-28">
                      <SelectValue>
                        {archivedFilter === "archived" ? "Archived" : "Active"}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="active">Active</SelectItem>
                      <SelectItem value="archived">Archived</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setLeftCollapsed((v) => !v)}
                    aria-label={leftCollapsed ? "Expand panel" : "Collapse panel"}
                    title={leftCollapsed ? "Expand panel" : "Collapse panel"}
                    className="ml-auto hidden h-9 w-9 shrink-0 md:inline-flex"
                  >
                    {leftCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
                  </Button>
                </>
              )}
            </div>
            <div className="flex-1 overflow-y-auto">
              {conversations.map((c) => {
                const isActive = c.id === selectedConvId;
                const isConfirm = confirmArchiveId === c.id;
                const isArchived = c.is_archived;
                const isUnread = c.unread_count > 0;
                return (
                  <div key={c.id} className="group relative flex border-b">
                    <button
                      type="button"
                      onClick={() => handleSelectConv(c.id)}
                      className={cn(
                        "flex min-w-0 flex-1 flex-col gap-1 px-4 py-3 text-left transition-colors",
                        isActive ? "bg-accent" : "hover:bg-accent/50"
                      )}
                    >
                      <div className="flex items-center gap-2 pr-16">
                        {c.unread_count > 0 && <span className="bg-primary mt-1 h-2 w-2 shrink-0 rounded-full" />}
                        <p className={cn("min-w-0 flex-1 truncate text-sm", c.unread_count > 0 ? "font-semibold" : "font-medium")}>
                          {c.title || "Untitled"}
                        </p>
                      </div>
                      <p className="text-muted-foreground line-clamp-2 pl-4 text-xs">{truncateEscaped(c.last_message_preview ?? "", 120)}</p>
                      <div className="flex items-center gap-2 pl-4">
                        <span className="text-muted-foreground shrink-0 text-[11px]">{formatListTime(c.last_message_at)}</span>
                        <div className="flex min-w-0 -space-x-1">
                          {c.participants.slice(0, 3).map((p) => {
                            const name = getParticipantDisplayName(
                              p as unknown as { display_name: string; first_name?: string | null; last_name?: string | null },
                            );
                            const pEmail = (p as unknown as { email?: string | null }).email ?? null;
                            return (
                              <UserAvatar
                                key={p.id}
                                name={name}
                                email={pEmail}
                                avatarUrl={p.avatar_url}
                                sizeClassName="h-5 w-5 border-2 border-background"
                                fallbackClassName="text-[9px]"
                                onClick={p.id === identity?.id ? undefined : () => setSelectedUser({ userId: p.id, fallback: { display_name: name, email: pEmail, avatar_url: p.avatar_url } })}
                              />
                            );
                          })}
                          {c.participants.length > 3 && (
                            <span className="text-muted-foreground bg-muted flex h-5 w-5 items-center justify-center rounded-full border-2 border-background text-[10px]">
                              +{c.participants.length - 3}
                            </span>
                          )}
                        </div>
                        {c.unread_count > 0 && (
                          <Badge variant="default" className="ml-auto h-5 shrink-0 px-1.5 text-xs">
                            {c.unread_count}
                          </Badge>
                        )}
                      </div>
                    </button>
                    <div
                      className={cn(
                        "absolute right-1 top-1.5 flex items-center gap-1 rounded-md border bg-background/95 p-1 shadow-sm backdrop-blur transition-opacity",
                        isConfirm ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-within:opacity-100"
                      )}
                    >
                      {isConfirm ? (
                        <>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            onClick={(e) => {
                              e.stopPropagation();
                              setConfirmArchiveId(null);
                            }}
                            aria-label="Cancel"
                            title="Cancel"
                          >
                            <X className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="destructive"
                            size="icon"
                            className="h-7 w-7"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleArchiveConversation(c.id, !isArchived);
                            }}
                            aria-label={isArchived ? "Confirm unarchive" : "Confirm archive"}
                            title={isArchived ? "Confirm unarchive" : "Confirm archive"}
                          >
                            <Check className="h-4 w-4" />
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleToggleRead(c);
                            }}
                            aria-label={isUnread ? "Mark as read" : "Mark as unread"}
                            title={isUnread ? "Mark as read" : "Mark as unread"}
                          >
                            {isUnread ? <MailOpen className="h-4 w-4" /> : <Mail className="h-4 w-4" />}
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            onClick={(e) => {
                              e.stopPropagation();
                              setConfirmArchiveId(c.id);
                            }}
                            aria-label={isArchived ? "Unarchive" : "Archive"}
                            title={isArchived ? "Unarchive" : "Archive"}
                          >
                            {isArchived ? <ArchiveRestore className="h-4 w-4" /> : <Archive className="h-4 w-4" />}
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
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
            {leftCollapsed && (
              <div className="hidden items-center gap-2 border-b bg-muted/30 px-3 py-2 md:flex">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0"
                  onClick={() => setLeftCollapsed(false)}
                  aria-label="Show conversations"
                  title="Show conversations"
                >
                  <PanelLeftOpen className="h-4 w-4" />
                </Button>
                <span className="text-muted-foreground text-sm">Conversations hidden</span>
              </div>
            )}
            {selectedConversation ? (
              <div className="flex min-h-0 flex-1 flex-col">
                {/* Thread header */}
                <div className="flex flex-col gap-3 border-b p-4">
                  {/* A failed refetch keeps the cached messages, and this header sits outside
                      the message scroller, so the note stays visible at any scroll position.
                      Always mounted: a live region has to be in the accessibility tree before
                      its text changes to be announced — `sr-only` keeps it out of the layout. */}
                  <p
                    role="status"
                    className={cn(
                      "flex items-center justify-between gap-2 text-sm",
                      !staleNote && "sr-only",
                      staleNote && (messagesRefused ? "text-destructive" : "text-muted-foreground"),
                    )}
                  >
                    <span>
                      {staleNote && (messagesRefused ? "Could not refresh messages." : "Showing the last messages loaded.")}
                    </span>
                    {staleNote && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void messagesQuery.refetch()}
                        disabled={messagesQuery.isFetching}
                        aria-label="Retry loading messages"
                      >
                        Retry
                      </Button>
                    )}
                  </p>
                  <div className="flex items-start gap-2">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0 mt-0.5"
                      onClick={() => setSelectedConvId(null)}
                      aria-label="Back"
                      title="Back"
                    >
                      <ArrowLeft className="h-4 w-4" />
                    </Button>
                    <div className="min-w-0 flex-1">
                      {editingTitle ? (
                        <div className="flex items-center gap-2">
                          <Input
                            value={editTitleValue}
                            onChange={(e) => setEditTitleValue(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") handleTitleSave();
                              if (e.key === "Escape") setEditingTitle(false);
                            }}
                            className="h-8"
                            placeholder="Conversation title"
                            autoFocus
                          />
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 shrink-0"
                            onClick={handleTitleSave}
                            aria-label="Save title"
                            title="Save title"
                          >
                            <Check className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 shrink-0"
                            onClick={() => setEditingTitle(false)}
                            aria-label="Cancel"
                            title="Cancel"
                          >
                            <X className="h-4 w-4" />
                          </Button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <h3 className="truncate text-lg font-semibold">{selectedConversation.title || "Untitled"}</h3>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6"
                            onClick={() => setEditingTitle(true)}
                            aria-label="Edit title"
                            title="Edit title"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      )}
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        {selectedConversation.participants.slice(0, 2).map((p) => {
                          const name = getParticipantDisplayName(
                            p as unknown as { display_name: string; first_name?: string | null; last_name?: string | null },
                          );
                          const pEmail = (p as unknown as { email?: string | null }).email ?? null;
                          const clickable = p.id !== identity?.id;
                          const badgeInner = (
                            <Badge
                              key={p.id}
                              variant="secondary"
                              className={clickable ? "cursor-pointer gap-1 hover:opacity-80" : "gap-1"}
                              {...(clickable
                                ? {
                                    role: "button" as const,
                                    tabIndex: 0,
                                    onClick: () =>
                                      setSelectedUser({ userId: p.id, fallback: { display_name: name, email: pEmail, avatar_url: p.avatar_url } }),
                                    onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => {
                                      if (e.key === "Enter" || e.key === " ") {
                                        e.stopPropagation();
                                        e.preventDefault();
                                        setSelectedUser({ userId: p.id, fallback: { display_name: name, email: pEmail, avatar_url: p.avatar_url } });
                                      }
                                    },
                                  }
                                : {})}
                            >
                              <UserAvatar
                                name={name}
                                email={pEmail}
                                avatarUrl={p.avatar_url}
                                sizeClassName="h-4 w-4"
                                fallbackClassName="text-[8px]"
                                firstName={(p as unknown as { first_name?: string | null }).first_name ?? null}
                                lastName={(p as unknown as { last_name?: string | null }).last_name ?? null}
                                onClick={p.id === identity?.id ? undefined : () => setSelectedUser({ userId: p.id, fallback: { display_name: name, email: pEmail, avatar_url: p.avatar_url } })}
                              />
                              {name}
                            </Badge>
                          );
                          return badgeInner;
                        })}
                        {selectedConversation.participants.length > 2 && (
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Badge
                                  variant="secondary"
                                  className="cursor-pointer px-2"
                                  aria-label={`+${selectedConversation.participants.length - 2} more recipients`}
                                  title={`+${selectedConversation.participants.length - 2} more`}
                                >
                                  …
                                </Badge>
                              </TooltipTrigger>
                              <TooltipContent side="bottom" align="start" className="max-w-[260px]">
                                <div className="flex flex-col gap-1 text-xs">
                                  {selectedConversation.participants.map((p) => {
                                    const name = getParticipantDisplayName(p as unknown as { display_name: string; first_name?: string | null; last_name?: string | null });
                                    return (
                                      <span key={p.id} className="truncate">
                                        {name}
                                      </span>
                                    );
                                  })}
                                </div>
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        )}
                        {canManageParticipants && (
                          <Button
                            variant="secondary"
                            size="icon"
                            className="h-5 w-5 shrink-0 rounded-full"
                            onClick={() => setEditParticipantsOpen(true)}
                            aria-label="Edit recipients"
                            title="Edit recipients"
                          >
                            <UserPlus className="h-3 w-3" />
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Messages */}
                <div data-testid="thread-messages" className="flex-1 overflow-y-auto p-4">
                  <div className="flex flex-col gap-4">
                    {messagesLoading ? (
                      <p className="text-muted-foreground text-sm">Loading…</p>
                    ) : messagesError && !hasCachedMessages ? (
                      <p className="text-destructive text-sm">Could not load messages.</p>
                    ) : !hasCachedMessages ? (
                      <p className="text-muted-foreground text-sm">No messages yet.</p>
                    ) : (
                      messages.map((m) => {
                        const isSelf = identity?.id === m.sender_id;
                        return (
                          <div key={m.id} className={cn("flex gap-3", isSelf ? "justify-end" : "justify-start")}>
                            {!isSelf && (
                              <UserAvatar
                                name={m.sender_name}
                                email={m.sender_email ?? null}
                                avatarUrl={m.sender_avatar_url ?? null}
                                sizeClassName="h-7 w-7 shrink-0"
                                fallbackClassName="text-xs"
                                onClick={m.sender_id === identity?.id ? undefined : () => setSelectedUser({ userId: m.sender_id, fallback: { display_name: m.sender_name, email: m.sender_email ?? null, avatar_url: m.sender_avatar_url ?? null } })}
                              />
                            )}
                            <div className={cn("max-w-[75%] rounded-lg px-3 py-2", isSelf ? "bg-primary text-primary-foreground" : "bg-muted")}>
                              {!isSelf && <p className="mb-1 text-xs font-medium opacity-70">{m.sender_name}</p>}
                              <div className={cn("prose prose-sm dark:prose-invert max-w-none break-words", isSelf ? "prose-invert" : "")}>
                                <Markdown
                                  components={isSelf ? markdownComponentsInverted : markdownComponents}
                                  remarkPlugins={mentionPlugins}
                                  urlTransform={mentionUrlTransform}
                                >
                                  {m.body}
                                </Markdown>
                              </div>
                              <p className={cn("mt-1 text-[11px]", isSelf ? "text-primary-foreground/70" : "text-muted-foreground")}>
                                {formatDate(m.created_at)}
                              </p>
                            </div>
                            {isSelf && (
                              <UserAvatar
                                name={m.sender_name}
                                email={m.sender_email ?? identity?.email ?? null}
                                avatarUrl={m.sender_avatar_url ?? null}
                                sizeClassName="h-7 w-7 shrink-0"
                                fallbackClassName="text-xs"
                              />
                            )}
                          </div>
                        );
                      })
                    )}
                    <div ref={messagesEndRef} />
                  </div>
                </div>

                <UserProfileDialog
                  userId={selectedUser?.userId ?? null}
                  open={!!selectedUser}
                  onOpenChange={(open) => {
                    if (!open) setSelectedUser(null);
                  }}
                  fallback={selectedUser?.fallback}
                />

                {/* Composer */}
                <div className="border-t p-3">
                  <div className="flex flex-col gap-2">
                    <TiptapEditor
                      value={draft}
                      onChange={(md, html) => {
                        setDraft(md);
                        setDraftHtml(html);
                      }}
                      onMention={setMentionIds}
                      mentions={mentionTargets}
                      placeholder="Write a message... Use @ to mention someone"
                      minHeight="60px"
                    />
                    <div className="flex justify-end">
                      <Button size="sm" onClick={handleSend} disabled={!draft.trim()}>
                        <SendHorizontal className="mr-1 h-3.5 w-3.5" />
                        Send
                      </Button>
                    </div>
                  </div>
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
          <div
            className={cn(
              "flex w-full flex-col overflow-hidden border-r transition-all duration-200",
              selectedNotif ? "hidden md:flex" : "flex",
              leftCollapsed ? "md:hidden" : "md:w-80 md:flex"
            )}
          >
            <div className="flex items-center gap-2 border-b p-3">
              <span className="shrink-0 text-sm font-medium">Notifications</span>
              <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as StatusFilter)}>
                <SelectTrigger className="h-9 w-28">
                  <SelectValue>
                    {STATUS_OPTIONS.find((o) => o.value === statusFilter)?.label}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="ml-auto flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={markAllRead}
                  disabled={markingAll || unreadCount === 0}
                  aria-label="Mark all as read"
                  title="Mark all as read"
                  className="h-9 w-9 shrink-0"
                >
                  <MailOpen className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setLeftCollapsed((v) => !v)}
                  aria-label={leftCollapsed ? "Expand panel" : "Collapse panel"}
                  title={leftCollapsed ? "Expand panel" : "Collapse panel"}
                  className="hidden h-9 w-9 shrink-0 md:inline-flex"
                >
                  {leftCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
                </Button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto">
              {allNotifications.map((n) => {
              const isActive = n.id === selectedNotif?.id;
              const isConvMsg = n.type === "conversation_message";
              return (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => handleSelectNotif(n)}
                  className={cn(
                    "flex w-full flex-col gap-1 border-b px-4 py-3 text-left transition-colors",
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
                  <p className="text-muted-foreground line-clamp-1 pl-4 text-xs">{truncateEscaped(n.body, 100)}</p>
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
          </div>

          <div className={cn("flex min-w-0 flex-1 flex-col overflow-y-auto", selectedNotif ? "flex" : "hidden md:flex")}>
            {leftCollapsed && (
              <div className="hidden items-center gap-2 border-b bg-muted/30 px-3 py-2 md:flex">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0"
                  onClick={() => setLeftCollapsed(false)}
                  aria-label="Show notifications"
                  title="Show notifications"
                >
                  <PanelLeftOpen className="h-4 w-4" />
                </Button>
                <span className="text-muted-foreground text-sm">Notifications hidden</span>
              </div>
            )}
            {selectedNotif ? (
              <div className="flex flex-1 flex-col p-6">
                <div className="mb-6 flex items-start gap-2">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={handleCloseNotif}
                    aria-label="Back"
                    title="Back"
                  >
                    <ArrowLeft className="h-4 w-4" />
                  </Button>
                  <div className="min-w-0 flex-1 flex flex-col gap-2">
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
                </div>
                <div className="prose prose-sm dark:prose-invert max-w-none flex-1">
                  <Markdown components={markdownComponents}>{selectedNotif.body || ""}</Markdown>
                </div>
                <div className="border-border mt-6 flex items-center gap-2 border-t pt-4">
                  {notificationLinkUrl(selectedNotif) && (
                    <Button size="sm" variant="outline" asChild>
                      <a href={notificationLinkUrl(selectedNotif)} target="_blank" rel="noopener noreferrer">
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
      {selectedConversation && (
        <EditParticipantsDialog
          open={editParticipantsOpen}
          onOpenChange={setEditParticipantsOpen}
          conversationId={selectedConversation.id}
          participantIds={selectedConversation.participants.map((p) => p.id)}
          onSaved={() => {
            convQuery.refetch();
            invalidate({ resource: "conversations", invalidates: ["list"] });
          }}
        />
      )}
    </div>
  );
}
