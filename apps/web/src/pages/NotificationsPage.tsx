import { useEffect, useState } from "react";
import { useUpdate, useUpdateMany, type CrudFilters } from "@refinedev/core";
import { useWorkspaceList } from "../hooks/useWorkspaceQuery";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Eye,
  Mail,
  MailOpen,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { ListView, ListViewHeader } from "../components/refine-ui/views/list-view";
import { EmptyRow, formatDate } from "../components/ui";
import type { Notification } from "../types";

type StatusFilter = "unread" | "read" | "all";

const PAGE_SIZE = 10;

const FILTER_OPTIONS: Array<{ value: StatusFilter; label: string }> = [
  { value: "unread", label: "Unread" },
  { value: "read", label: "Read" },
  { value: "all", label: "All" },
];

function ReadBadge({ acknowledged }: { acknowledged: boolean }) {
  return (
    <Badge variant={acknowledged ? "secondary" : "default"}>
      {acknowledged ? "Read" : "Unread"}
    </Badge>
  );
}

export function NotificationsPage() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("unread");
  const [current, setCurrent] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [viewing, setViewing] = useState<Notification | null>(null);

  const filters: CrudFilters =
    statusFilter === "all"
      ? []
      : [
          {
            field: "acknowledged",
            operator: "eq",
            value: statusFilter === "unread" ? "false" : "true",
          },
        ];

  const { result, query } = useWorkspaceList<Notification>({
    resource: "notifications",
    pagination: { currentPage: current, pageSize: PAGE_SIZE },
    sorters: [{ field: "created_at", order: "desc" }],
    filters,
  });
  const { mutate: updateOne } = useUpdate();
  const { mutate: updateMany } = useUpdateMany();

  const items = result?.data ?? [];
  const total = result?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  useEffect(() => {
    if (current > totalPages) setCurrent(totalPages);
  }, [current, totalPages]);

  const setStatus = (value: StatusFilter) => {
    setStatusFilter(value);
    setCurrent(1);
    setSelected(new Set());
  };

  const toggleSelected = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const pageIds = items.map((n) => n.id);
  const allSelected = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
  const someSelected = pageIds.some((id) => selected.has(id));

  const setPageSelection = (checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of pageIds) {
        if (checked) {
          next.add(id);
        } else {
          next.delete(id);
        }
      }
      return next;
    });
  };

  const markRead = (id: string) =>
    updateOne({ resource: "notifications", id, values: { acknowledged: true } });

  const markUnread = (id: string) =>
    updateOne({ resource: "notifications", id, values: { acknowledged: false } });

  const bulkSet = (acknowledged: boolean) => {
    if (selected.size === 0) return;
    updateMany({
      resource: "notifications",
      ids: [...selected],
      values: { acknowledged },
      successNotification: {
        message: acknowledged
          ? `${selected.size} notification${selected.size > 1 ? "s" : ""} marked as read`
          : `${selected.size} notification${selected.size > 1 ? "s" : ""} marked as unread`,
        type: "success",
      },
    });
    setSelected(new Set());
  };

  const openView = (n: Notification) => {
    setViewing(n);
    if (!n.acknowledged) {
      markRead(n.id);
    }
  };

  const toggleViewing = () => {
    if (!viewing) return;
    if (viewing.acknowledged) {
      markUnread(viewing.id);
    } else {
      markRead(viewing.id);
    }
    setViewing({ ...viewing, acknowledged: !viewing.acknowledged });
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(viewing.id);
      return next;
    });
    query.refetch();
  };

  return (
    <ListView>
      <ListViewHeader title="Notifications" canCreate={false} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Select value={statusFilter} onValueChange={setStatus}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FILTER_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {selected.size > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground text-sm">{selected.size} selected</span>
            <Button size="sm" variant="outline" onClick={() => bulkSet(true)}>
              <Check className="mr-1 h-4 w-4" />
              Mark as read
            </Button>
            <Button size="sm" variant="outline" onClick={() => bulkSet(false)}>
              <Mail className="mr-1 h-4 w-4" />
              Mark as unread
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
              Clear
            </Button>
          </div>
        )}
      </div>

      <div className="border-border overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">
                <Checkbox
                  aria-label="Select all on page"
                  checked={allSelected ? true : someSelected ? "indeterminate" : false}
                  onCheckedChange={(v) => setPageSelection(v === true)}
                />
              </TableHead>
              <TableHead>Notification</TableHead>
              <TableHead>Workspace</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Received</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((n) => (
              <TableRow
                key={n.id}
                className={selected.has(n.id) ? "bg-accent/40" : undefined}
              >
                <TableCell>
                  <Checkbox
                    aria-label={`Select ${n.title}`}
                    checked={selected.has(n.id)}
                    onCheckedChange={() => toggleSelected(n.id)}
                  />
                </TableCell>
                <TableCell>
                  <button
                    type="button"
                    onClick={() => openView(n)}
                    className="block max-w-md cursor-pointer text-left"
                  >
                    <p className="font-medium hover:underline">{n.title}</p>
                    <p className="text-muted-foreground line-clamp-1 text-xs">{n.body}</p>
                  </button>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {n.workspace_name ?? "—"}
                </TableCell>
                <TableCell className="text-muted-foreground">{n.type}</TableCell>
                <TableCell>
                  <ReadBadge acknowledged={n.acknowledged} />
                </TableCell>
                <TableCell className="text-muted-foreground">{formatDate(n.created_at)}</TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-1">
                    <Button variant="ghost" size="sm" onClick={() => openView(n)}>
                      <Eye className="mr-1 h-3.5 w-3.5" />
                      View
                    </Button>
                    {n.acknowledged ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        title="Mark as unread"
                        onClick={() => markUnread(n.id)}
                      >
                        <Mail className="mr-1 h-3.5 w-3.5" />
                        Unread
                      </Button>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        title="Mark as read"
                        onClick={() => markRead(n.id)}
                      >
                        <MailOpen className="mr-1 h-3.5 w-3.5" />
                        Read
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {items.length === 0 && (
              <EmptyRow colSpan={7}>
                {statusFilter === "unread"
                  ? "No unread notifications."
                  : statusFilter === "read"
                    ? "No read notifications."
                    : "No notifications yet."}
              </EmptyRow>
            )}
          </TableBody>
        </Table>
      </div>

      {total > PAGE_SIZE && (
      <div className="flex items-center justify-between gap-2">
        <p className="text-muted-foreground text-sm">
          Showing {(current - 1) * PAGE_SIZE + 1}–{Math.min(current * PAGE_SIZE, total)} of {total}
        </p>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            disabled={current <= 1}
            onClick={() => setCurrent((c) => Math.max(1, c - 1))}
          >
            <ChevronLeft className="h-4 w-4" />
            Previous
          </Button>
          <span className="text-muted-foreground px-2 text-sm">
            Page {current} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={current >= totalPages}
            onClick={() => setCurrent((c) => Math.min(totalPages, c + 1))}
          >
            Next
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
      )}

      <Dialog open={viewing !== null} onOpenChange={(open) => !open && setViewing(null)}>
        <DialogContent className="max-w-lg">
          {viewing && (
            <>
              <DialogHeader>
                <DialogTitle>{viewing.title}</DialogTitle>
                <DialogDescription>
                  {viewing.type} · {viewing.workspace_name ?? "Unknown workspace"} ·{" "}
                  {formatDate(viewing.created_at)}
                </DialogDescription>
              </DialogHeader>
              <div className="flex min-w-0 flex-col gap-4">
                {viewing.body && <p className="text-sm">{viewing.body}</p>}
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground text-sm">Status:</span>
                  <ReadBadge acknowledged={viewing.acknowledged} />
                </div>
                {viewing.payload && Object.keys(viewing.payload).length > 0 && (
                  <div className="flex min-w-0 flex-col gap-1">
                    <span className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
                      Details
                    </span>
                    <pre className="border-border bg-muted max-h-48 min-w-0 overflow-auto rounded-lg border p-3 text-xs">
                      {JSON.stringify(viewing.payload, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={toggleViewing}>
                  {viewing.acknowledged ? (
                    <>
                      <Mail className="mr-1 h-4 w-4" />
                      Mark as unread
                    </>
                  ) : (
                    <>
                      <Check className="mr-1 h-4 w-4" />
                      Mark as read
                    </>
                  )}
                </Button>
                <Button variant="secondary" onClick={() => setViewing(null)}>
                  Close
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </ListView>
  );
}
