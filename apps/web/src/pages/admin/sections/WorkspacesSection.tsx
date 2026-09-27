import { useState } from "react";
import { useList, type CrudFilters } from "@refinedev/core";
import { Building2, ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyRow, formatDate } from "@/components/ui";
import { useAdminGuard } from "./AdminLayout";

export type AdminWorkspace = {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  member_count: number;
  created_at?: string;
};

const PAGE_SIZE = 20;

export function WorkspacesSection() {
  const { isSuperuser } = useAdminGuard();
  const [search, setSearch] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [current, setCurrent] = useState(1);

  const filters: CrudFilters = submitted
    ? [{ field: "name", operator: "contains", value: submitted }]
    : [];
  const { result, query } = useList<AdminWorkspace>({
    resource: "admin-workspaces",
    pagination: { currentPage: current, pageSize: PAGE_SIZE, mode: "server" },
    filters,
    sorters: [{ field: "created_at", order: "desc" }],
    queryOptions: { enabled: isSuperuser },
  });

  const rows = result?.data ?? [];
  const total = result?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const isLoading = query.isPending;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Workspaces</CardTitle>
          <CardDescription>
            Every workspace on the deployment, with member counts. Search and paging run
            against the database — only {PAGE_SIZE} rows load per page.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setSubmitted(search.trim());
              setCurrent(1);
            }}
          >
            <Input
              placeholder="Search by name…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Button type="submit">Search</Button>
          </form>
          <div className="border-border overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Slug</TableHead>
                  <TableHead>Members</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <EmptyRow colSpan={4}>Loading…</EmptyRow>
                ) : (
                  rows.map((w) => (
                    <TableRow key={w.id}>
                      <TableCell>
                        <span className="flex items-center gap-2 font-medium">
                          <Building2 className="text-muted-foreground h-4 w-4" />
                          {w.name}
                        </span>
                      </TableCell>
                      <TableCell className="text-muted-foreground font-mono text-xs">
                        {w.slug}
                      </TableCell>
                      <TableCell>{w.member_count}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(w.created_at)}
                      </TableCell>
                    </TableRow>
                  ))
                )}
                {!isLoading && rows.length === 0 && (
                  <EmptyRow colSpan={4}>No workspaces found</EmptyRow>
                )}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between gap-2">
            <p className="text-muted-foreground text-sm">
              Showing {total === 0 ? 0 : (current - 1) * PAGE_SIZE + 1}–{Math.min(current * PAGE_SIZE, total)} of {total}
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
        </CardContent>
      </Card>
    </div>
  );
}
