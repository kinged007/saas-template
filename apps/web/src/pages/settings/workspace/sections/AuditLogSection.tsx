import { useState } from "react";
import {  } from "@refinedev/core";
import { useWorkspaceList } from "../../../../hooks/useWorkspaceQuery";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyRow, formatDate } from "@/components/ui";
import type { AuditLogEntry } from "@/types";

export function AuditLogSection() {
  const [page, setPage] = useState(1);
  const pageSize = 20;

  const { result, query } = useWorkspaceList<AuditLogEntry>({
    resource: "audit",
    pagination: { currentPage: page, pageSize },
    sorters: [{ field: "created_at", order: "desc" }],
  });

  const rows = result?.data ?? [];
  const total = result?.total ?? rows.length;
  const isLoading = query.isPending;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Audit Log</CardTitle>
          <CardDescription>
            Immutable trail of workspace actions (workspace edits, member changes, role/invitation/api-key events). Filter
            and sort support is available via the table query — narrow by <code>action</code> or{" "}
            <code>resource_type</code> using the API filter syntax.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Resource</TableHead>
                  <TableHead>Details</TableHead>
                  <TableHead>IP</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <EmptyRow colSpan={6}>Loading…</EmptyRow>
                ) : (
                  rows.map((entry) => (
                    <TableRow key={entry.id}>
                      <TableCell className="text-muted-foreground whitespace-nowrap text-xs">
                        {formatDate(entry.created_at)}
                      </TableCell>
                      <TableCell>
                        <span className="text-sm font-medium">{entry.actor_display_name ?? "—"}</span>
                        {entry.actor_user_id && (
                          <span className="text-muted-foreground ml-1 font-mono text-xs">{entry.actor_user_id.slice(0, 8)}</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-xs font-mono">
                          {entry.action}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <span className="text-xs">
                          {entry.resource_type}
                          <span className="text-muted-foreground"> / {entry.resource_id.slice(0, 8)}</span>
                        </span>
                      </TableCell>
                      <TableCell className="max-w-xs">
                        <span className="text-muted-foreground truncate text-xs" title={JSON.stringify(entry.details)}>
                          {entry.details && Object.keys(entry.details).length > 0 ? JSON.stringify(entry.details) : "—"}
                        </span>
                      </TableCell>
                      <TableCell className="text-muted-foreground font-mono text-xs">{entry.ip_address ?? "—"}</TableCell>
                    </TableRow>
                  ))
                )}
                {!isLoading && rows.length === 0 && <EmptyRow colSpan={6}>No audit entries yet.</EmptyRow>}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between border-t px-4 py-3">
            <span className="text-muted-foreground text-sm">
              {total} {total === 1 ? "entry" : "entries"} · page {page} of {totalPages}
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                Next
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
