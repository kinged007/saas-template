import { useState } from "react";
import { useGetIdentity } from "@refinedev/core";

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
import type { Identity } from "../types";

type AdminUser = {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  is_superuser: boolean;
  created_at?: string;
  workspaces?: Array<{ id: string; name: string; slug: string; role: string }>;
};

const errMsg = (e: unknown) => (e instanceof Error ? e.message : "Request failed");

export function AdminPage() {
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  const [search, setSearch] = useState("");
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (identity && identity.is_superuser !== true) {
    return (
      <ListView>
        <ListViewHeader title="Admin" />
        <p className="text-muted-foreground text-sm">Access denied — superuser only.</p>
      </ListView>
    );
  }

  const runSearch = async () => {
    setError(null);
    setBusy(true);
    try {
      const res = await httpClient.get(`${API_URL}/admin/users?search=${encodeURIComponent(search)}`);
      setUsers(res.data ?? []);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const openUser = async (id: string) => {
    setError(null);
    setBusy(true);
    try {
      const res = await httpClient.get(`${API_URL}/admin/users/${id}`);
      setSelected(res.data);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async (user: AdminUser, isActive: boolean) => {
    setError(null);
    setBusy(true);
    try {
      const res = await httpClient.patch(`${API_URL}/admin/users/${user.id}`, { is_active: isActive });
      const updated = res.data as AdminUser;
      setSelected((s) => (s?.id === updated.id ? { ...s, ...updated } : s));
      setUsers((list) => list?.map((u) => (u.id === updated.id ? { ...u, ...updated } : u)) ?? list);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ListView>
      <ListViewHeader title="Admin" />
      {error && <p className="text-destructive text-sm">{error}</p>}
      <div className="flex items-end gap-2">
        <div className="grid gap-1.5">
          <Label htmlFor="admin-search">Find user by email or name</Label>
          <Input
            id="admin-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="user@example.com"
            onKeyDown={(e) => e.key === "Enter" && void runSearch()}
          />
        </div>
        <Button onClick={() => void runSearch()} disabled={busy || !search.trim()}>
          Search
        </Button>
      </div>
      {users !== null && (
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
            {users.length === 0 && <EmptyRow colSpan={4}>No users found</EmptyRow>}
            {users.map((u) => (
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
                onClick={() => void toggleActive(selected, !selected.is_active)}
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
