import { useState } from "react";
import { useList, type CrudFilters } from "@refinedev/core";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyRow, formatDate } from "@/components/ui";
import { errorMessage } from "@/utils/errorMessage";
import type { AuditLogEntry } from "@/types";

export type AuditEntry = AuditLogEntry & {
  workspace_name?: string | null;
  actor_email?: string | null;
};

/** Compact two-line timestamp for dense tables: date on top, time below. */
function formatShortDateTime(value?: string | null): { date: string; time: string } {
  if (!value) return { date: "—", time: "" };
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return { date: "—", time: "" };
  return {
    date: d.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    time: d.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }),
  };
}

function DetailRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-2 py-1.5 text-sm">
      <dt className="text-muted-foreground shrink-0">{label}</dt>
      <dd className={mono ? "font-mono text-xs break-all" : "break-words"}>{value}</dd>
    </div>
  );
}

const PAGE_SIZE = 20;

export function AuditLogTable({
  resource,
  searchPlaceholder,
  searchEnabled,
  showWorkspace,
}: {
  resource: string;
  searchPlaceholder: string;
  searchEnabled: boolean;
  showWorkspace: boolean;
}) {
  const [search, setSearch] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [current, setCurrent] = useState(1);
  const [viewing, setViewing] = useState<AuditEntry | null>(null);

  const filters: CrudFilters =
    searchEnabled && submitted
      ? [{ field: "q", operator: "contains", value: submitted }]
      : [];
  const { result, query } = useList<AuditEntry>({
    resource,
    pagination: { currentPage: current, pageSize: PAGE_SIZE, mode: "server" },
    filters,
    sorters: [{ field: "created_at", order: "desc" }],
    // The failure row below reports the reason itself, so refine's error
    // notification would only repeat it in a toast.
    errorNotification: false,
  });

  const rows = result?.data ?? [];
  const total = result?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const isLoading = query.isPending;
  // refine types the query result without `isError`; without it a refusal falls
  // through to `rows.length === 0` and claims the log is empty. Gating on the
  // row count keeps a failed background refetch from blanking loaded rows.
  const { isError = false, error } = query as unknown as {
    isError?: boolean;
    error?: unknown;
  };
  const failed = isError && rows.length === 0;
  const colSpan = showWorkspace ? 6 : 5;

  return (
    <>
      {searchEnabled && (
        <form
          className="flex gap-2 px-4"
          onSubmit={(e) => {
            e.preventDefault();
            setSubmitted(search.trim());
            setCurrent(1);
          }}
        >
          <Input
            placeholder={searchPlaceholder}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <Button type="submit">Search</Button>
        </form>
      )}
      <div className="overflow-x-auto">
        <Table className="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className="w-24">When</TableHead>
              {showWorkspace && <TableHead className="w-36">Workspace</TableHead>}
              <TableHead className="w-36">Actor</TableHead>
              <TableHead className="w-44">Action</TableHead>
              <TableHead className="w-36">Resource</TableHead>
              <TableHead className="w-28">IP</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <EmptyRow colSpan={colSpan}>Loading…</EmptyRow>
            ) : failed ? (
              <EmptyRow colSpan={colSpan}>
                Could not load audit entries. {errorMessage(error)}
              </EmptyRow>
            ) : rows.length === 0 ? (
              <EmptyRow colSpan={colSpan}>No audit entries yet.</EmptyRow>
            ) : (
              rows.map((entry) => (
                <TableRow
                  key={entry.id}
                  className="cursor-pointer"
                  onClick={() => setViewing(entry)}
                >
                  <TableCell className="text-muted-foreground text-xs">
                    {(() => {
                      const { date, time } = formatShortDateTime(entry.created_at);
                      return (
                        <span title={formatDate(entry.created_at)}>
                          <span className="block leading-tight">{date}</span>
                          <span className="block font-mono leading-tight">{time}</span>
                        </span>
                      );
                    })()}
                  </TableCell>
                  {showWorkspace && (
                    <TableCell
                      className="truncate text-sm"
                      title={entry.workspace_name ?? entry.workspace_id ?? ""}
                    >
                      {entry.workspace_name ?? (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  )}
                  <TableCell
                    className="truncate text-sm"
                    title={entry.actor_email ?? entry.actor_user_id ?? ""}
                  >
                    {entry.actor_display_name ?? (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="truncate">
                    <Badge variant="outline" className="max-w-full truncate text-xs font-mono">
                      {entry.action}
                    </Badge>
                  </TableCell>
                  <TableCell className="truncate font-mono text-xs" title={entry.resource_id}>
                    {entry.resource_type} / {entry.resource_id.slice(0, 8)}
                  </TableCell>
                  <TableCell className="text-muted-foreground truncate font-mono text-xs">
                    {entry.ip_address ?? "—"}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
      {!failed && (
        <div className="flex items-center justify-between border-t px-4 py-3">
          <span className="text-muted-foreground text-sm">
            Showing {total === 0 ? 0 : (current - 1) * PAGE_SIZE + 1}–
            {Math.min(current * PAGE_SIZE, total)} of {total}
          </span>
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
                <DialogTitle className="font-mono text-sm">{viewing.action}</DialogTitle>
                <DialogDescription>{formatDate(viewing.created_at)}</DialogDescription>
              </DialogHeader>
              <dl className="border-border divide-y rounded-lg border px-4">
                <DetailRow label="Entry ID" value={viewing.id} mono />
                {showWorkspace && (
                  <>
                    <DetailRow label="Workspace" value={viewing.workspace_name ?? "—"} />
                    <DetailRow label="Workspace ID" value={viewing.workspace_id ?? "—"} mono />
                  </>
                )}
                <DetailRow
                  label="Actor"
                  value={
                    [viewing.actor_display_name, viewing.actor_email]
                      .filter(Boolean)
                      .join(" · ") || "—"
                  }
                />
                <DetailRow label="Actor ID" value={viewing.actor_user_id ?? "—"} mono />
                <DetailRow
                  label="Resource"
                  value={`${viewing.resource_type} / ${viewing.resource_id}`}
                  mono
                />
                <DetailRow label="IP" value={viewing.ip_address ?? "—"} mono />
              </dl>
              <div className="flex min-w-0 flex-col gap-1">
                <span className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
                  Details
                </span>
                <pre className="border-border bg-muted max-h-48 min-w-0 overflow-auto rounded-lg border p-3 text-xs">
                  {JSON.stringify(viewing.details ?? {}, null, 2)}
                </pre>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

export function AuditLogCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 p-0">{children}</CardContent>
      </Card>
    </div>
  );
}
