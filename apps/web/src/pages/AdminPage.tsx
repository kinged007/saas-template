import { useState } from "react";
import { useGetIdentity, useList, useUpdate } from "@refinedev/core";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ListView, ListViewHeader } from "../components/refine-ui/views/list-view";
import { EmptyRow, StatusBadge, formatDate } from "../components/ui";

import { IDENTITY_QUERY_OPTIONS } from "../contexts/WorkspaceContext";
import { API_URL, httpClient } from "../providers/dataProvider";
import type { AdminUser, Identity } from "../types";

const errMsg = (e: unknown) => (e instanceof Error ? e.message : "Request failed");

export function AdminPage() {
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  const [search, setSearch] = useState("");
  const [submittedSearch, setSubmittedSearch] = useState<string | null>(null);
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);

  const { result: usersResult, query: usersQuery } = useList<AdminUser>({
    resource: "admin-users",
    filters: submittedSearch ? [{ field: "search", operator: "eq", value: submittedSearch }] : [],
    queryOptions: { enabled: submittedSearch !== null },
  });
  const { mutate: toggleActive, mutation } = useUpdate<AdminUser>();

  if (identity && identity.is_superuser !== true) {
    return (
      <ListView>
        <ListViewHeader title="Admin" />
        <p className="text-muted-foreground text-sm">Access denied — superuser only.</p>
      </ListView>
    );
  }

  const users = usersResult?.data ?? null;
  const listError = usersQuery.isError ? errMsg(usersQuery.error) : null;
  const busy = usersQuery.isFetching || mutation.isPending || detailBusy;

  const openUser = async (id: string) => {
    setDetailError(null);
    setDetailBusy(true);
    try {
      const res = await httpClient.get(`${API_URL}/admin/users/${id}`);
      setSelected(res.data);
    } catch (e) {
      setDetailError(errMsg(e));
    } finally {
      setDetailBusy(false);
    }
  };

  const onToggleActive = (user: AdminUser, isActive: boolean) => {
    setDetailError(null);
    toggleActive(
      {
        resource: "admin-users",
        id: user.id,
        values: { is_active: isActive },
        successNotification: {
          message: isActive ? "User enabled" : "User disabled",
          type: "success",
        },
        errorNotification: false,
      },
      {
        onSuccess: (response) => {
          const updated = (response as { data?: AdminUser }).data;
          if (updated) setSelected((s) => (s?.id === updated.id ? { ...s, ...updated } : s));
        },
        onError: (e) => setDetailError(errMsg(e)),
      },
    );
  };

  return (
    <ListView>
      <ListViewHeader title="Admin" />
      {(listError ?? detailError) && <p className="text-destructive text-sm">{listError ?? detailError}</p>}
      <div className="flex items-end gap-2">
        <div className="grid gap-1.5">
          <Label htmlFor="admin-search">Find user by email or name</Label>
          <Input
            id="admin-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="user@example.com"
            onKeyDown={(e) => e.key === "Enter" && setSubmittedSearch(search.trim())}
          />
        </div>
        <Button onClick={() => setSubmittedSearch(search.trim())} disabled={busy || !search.trim()}>
          Search
        </Button>
      </div>
      {submittedSearch !== null && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Joined</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {users !== null && users.length === 0 && !usersQuery.isFetching && (
              <EmptyRow colSpan={4}>No users found</EmptyRow>
            )}
            {(users ?? []).map((u) => (
              <TableRow key={u.id}>
                <TableCell>{u.email}</TableCell>
                <TableCell>
                  <StatusBadge status={u.is_active ? "active" : "disabled"} />
                </TableCell>
                <TableCell>{formatDate(u.created_at)}</TableCell>
                <TableCell>
                  <Button variant="outline" size="sm" onClick={() => void openUser(u.id)}>
                    Inspect
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {selected && (
        <div className="rounded-lg border p-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-medium">{selected.email}</h3>
              <p className="text-muted-foreground text-sm">
                {selected.workspaces?.length ?? 0} workspace(s)
                {selected.is_superuser ? " · superuser" : ""}
              </p>
            </div>
            {selected.id !== identity?.id && (
              <Button
                variant={selected.is_active ? "destructive" : "default"}
                size="sm"
                disabled={busy}
                onClick={() => onToggleActive(selected, !selected.is_active)}
              >
                {selected.is_active ? "Disable access" : "Enable access"}
              </Button>
            )}
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Workspace</TableHead>
                <TableHead>Role</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(selected.workspaces ?? []).map((w) => (
                <TableRow key={w.id}>
                  <TableCell>{w.name}</TableCell>
                  <TableCell>{w.role}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </ListView>
  );
}
