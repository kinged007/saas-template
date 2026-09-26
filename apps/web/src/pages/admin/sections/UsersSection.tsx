import { useState } from "react";
import {
  useCustom,
  useCustomMutation,
  useList,
  type CrudFilters,
} from "@refinedev/core";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyRow, StatusBadge, formatDate } from "@/components/ui";
import { useAdminGuard } from "./AdminLayout";

export type AdminUser = {
  id: string;
  email: string;
  display_name: string;
  is_superuser: boolean;
  is_active: boolean;
  created_at?: string;
};

type AdminUserDetail = AdminUser & {
  workspaces: { id: string; name: string; slug: string; role: string }[];
};

const PAGE_SIZE = 20;

export function UsersSection() {
  const { identity, isSuperuser } = useAdminGuard();
  const [search, setSearch] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [current, setCurrent] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const filters: CrudFilters = submitted
    ? [{ field: "email", operator: "contains", value: submitted }]
    : [];
  const { result, query } = useList<AdminUser>({
    resource: "admin-users",
    pagination: { currentPage: current, pageSize: PAGE_SIZE, mode: "server" },
    filters,
    sorters: [{ field: "created_at", order: "desc" }],
    queryOptions: { enabled: isSuperuser },
  });
  const detailQuery = useCustom<AdminUserDetail>({
    url: selectedId ? `admin/users/${selectedId}` : "",
    method: "get",
    queryOptions: { enabled: isSuperuser && selectedId !== null },
  });
  const { mutate: setActive, mutation } = useCustomMutation<AdminUserDetail>();

  const rows = result?.data ?? [];
  const total = result?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const rawDetail = detailQuery.result?.data;
  const detail =
    rawDetail && Array.isArray((rawDetail as AdminUserDetail).workspaces)
      ? (rawDetail as AdminUserDetail)
      : undefined;

  const toggle = (user: AdminUserDetail, next: boolean) => {
    setActive(
      {
        url: `admin/users/${user.id}`,
        method: "patch",
        values: { is_active: next },
        successNotification: {
          message: next ? "Account re-enabled" : "Account disabled",
          type: "success",
        },
        errorNotification: false,
      },
      {
        onSuccess: () => {
          void query.refetch();
          void detailQuery.query.refetch();
        },
      },
    );
  };

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Users</CardTitle>
          <CardDescription>
            Look up accounts, inspect workspace membership, and disable access. Search and
            paging run against the database — only {PAGE_SIZE} rows load per page.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setSubmitted(search.trim());
              setCurrent(1);
              setSelectedId(null);
            }}
          >
            <Input
              placeholder="Search by email…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Button type="submit">Search</Button>
          </form>
          <div className="border-border overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell>{u.email}</TableCell>
                    <TableCell>{u.display_name}</TableCell>
                    <TableCell>
                      <StatusBadge status={u.is_active ? "active" : "disabled"} />
                    </TableCell>
                    <TableCell>{formatDate(u.created_at)}</TableCell>
                    <TableCell className="text-right">
                      <Button variant="outline" size="sm" onClick={() => setSelectedId(u.id)}>
                        Inspect
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {rows.length === 0 && <EmptyRow colSpan={5}>No users found</EmptyRow>}
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
          {detail && (
            <div className="border-border rounded-lg border p-4">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="font-medium">
                  {detail.email} — {detail.workspaces.length} workspace(s)
                </h3>
                {detail.id !== identity?.id && (
                  <Button
                    variant={detail.is_active ? "destructive" : "default"}
                    size="sm"
                    disabled={mutation.isPending}
                    onClick={() => toggle(detail, !detail.is_active)}
                  >
                    {detail.is_active ? "Disable access" : "Re-enable"}
                  </Button>
                )}
              </div>
              <ul className="text-sm">
                {detail.workspaces.map((w) => (
                  <li key={w.id}>
                    {w.name} ({w.slug}) — {w.role}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
