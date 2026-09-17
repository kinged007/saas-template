import { useState } from "react";
import { useCustom, useCustomMutation, useGetIdentity } from "@refinedev/core";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ListView, ListViewHeader } from "@/components/refine-ui/views/list-view";
import { EmptyRow, StatusBadge, formatDate } from "@/components/ui";
import { IDENTITY_QUERY_OPTIONS } from "@/contexts/WorkspaceContext";
import type { Identity } from "@/types";

type AdminUser = {
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

export function AdminPage() {
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  const [search, setSearch] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const isSuperuser = identity?.is_superuser === true;

  const { result, query } = useCustom<AdminUser[]>({
    url: "admin/users",
    method: "get",
    config: { query: submitted ? { email_like: submitted } : {} },
    queryOptions: { enabled: isSuperuser },
  });
  const detailQuery = useCustom<AdminUserDetail>({
    url: `admin/users/${selectedId}`,
    method: "get",
    queryOptions: { enabled: isSuperuser && selectedId !== null },
  });
  const { mutate: setActive, mutation } = useCustomMutation<AdminUserDetail>();

  if (!isSuperuser) {
    return (
      <ListView>
        <ListViewHeader title="Administration" canCreate={false} />
        <p className="text-muted-foreground text-sm">Access denied — superuser only.</p>
      </ListView>
    );
  }

  const rows = Array.isArray(result?.data) ? result.data : [];
  const detail = detailQuery.result?.data;

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
      { onSuccess: () => void query.refetch() },
    );
  };

  return (
    <ListView>
      <ListViewHeader title="Administration" canCreate={false} />
      <form
        className="mb-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(search.trim());
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
      {detail && (
        <div className="border-border mt-4 rounded-lg border p-4">
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
    </ListView>
  );
}
