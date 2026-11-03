import { useState } from "react";
import { useCustom, useCustomMutation, useList, type CrudFilters } from "@refinedev/core";
import { Building2, ChevronLeft, ChevronRight } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyRow, StatusBadge, formatDate } from "@/components/ui";
import { useAdminGuard } from "./AdminLayout";
import { errorMessage } from "@/utils/errorMessage";

export type AdminWorkspace = {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  member_count: number;
  created_at?: string;
};

export type AdminWorkspaceMember = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
};

export type AdminWorkspaceDetail = AdminWorkspace & {
  members: AdminWorkspaceMember[];
};

const PAGE_SIZE = 20;

function asAdminWorkspaceDetail(raw: unknown): AdminWorkspaceDetail | undefined {
  const { id, members } = (raw ?? {}) as Partial<AdminWorkspaceDetail>;
  return typeof id === "string" && id.length > 0 && Array.isArray(members)
    ? (raw as AdminWorkspaceDetail)
    : undefined;
}

function WorkspaceEditForm({
  detail,
  onSaved,
}: {
  detail: AdminWorkspaceDetail;
  onSaved: () => void;
}) {
  const [name, setName] = useState(detail.name);
  const [slug, setSlug] = useState(detail.slug);
  const [description, setDescription] = useState(detail.description ?? "");
  const { mutate, mutation } = useCustomMutation();

  const save = () => {
    mutate(
      {
        url: `admin/workspaces/${detail.id}`,
        method: "patch",
        values: { name: name.trim(), slug: slug.trim(), description },
        successNotification: { message: "Workspace updated", type: "success" },
        errorNotification: false,
      } as never,
      {
        onSuccess: onSaved,
        onError: (e) => {
          toast.error(errorMessage(e));
        },
      }
    );
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-ws-name">Name</Label>
          <Input
            id="admin-ws-name"
            value={name}
            maxLength={150}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-ws-slug">Slug</Label>
          <Input
            id="admin-ws-slug"
            value={slug}
            maxLength={100}
            className="font-mono text-xs"
            onChange={(e) => setSlug(e.target.value)}
          />
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="admin-ws-description">Description</Label>
        <Textarea
          id="admin-ws-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className="flex justify-end">
        <Button size="sm" disabled={mutation.isPending || !name.trim() || !slug.trim()} onClick={save}>
          {mutation.isPending ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

export function WorkspacesSection() {
  const { isSuperuser } = useAdminGuard();
  const [search, setSearch] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [current, setCurrent] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);

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
  const detailQuery = useCustom<AdminWorkspaceDetail>({
    url: selectedId ? `admin/workspaces/${selectedId}` : "",
    method: "get",
    queryOptions: { enabled: isSuperuser && selectedId !== null },
  });

  const rows = result?.data ?? [];
  const total = result?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const isLoading = query.isPending;
  const detail = asAdminWorkspaceDetail(detailQuery.result?.data);

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
              setSelectedId(null);
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
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <EmptyRow colSpan={5}>Loading…</EmptyRow>
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
                      <TableCell className="text-right">
                        <Button variant="outline" size="sm" onClick={() => setSelectedId(w.id)}>
                          Inspect
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
                {!isLoading && rows.length === 0 && (
                  <EmptyRow colSpan={5}>No workspaces found</EmptyRow>
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
          {detail && (
            <div className="border-border flex flex-col gap-4 rounded-lg border p-4">
              <div className="flex items-center justify-between">
                <h3 className="font-medium">
                  {detail.name} — {detail.member_count} member(s)
                </h3>
                <p className="text-muted-foreground text-xs">Created {formatDate(detail.created_at)}</p>
              </div>
              <WorkspaceEditForm
                key={detail.id}
                detail={detail}
                onSaved={() => {
                  void query.refetch();
                  void detailQuery.query.refetch();
                }}
              />
              <ul className="flex flex-col gap-1 text-sm">
                {detail.members.map((m) => (
                  <li key={m.id} className="flex items-center gap-2">
                    <StatusBadge status={m.is_active ? "active" : "disabled"} />
                    <span className="font-medium">{m.display_name}</span>
                    <span className="text-muted-foreground text-xs">
                      {m.email} — {m.role}
                    </span>
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
