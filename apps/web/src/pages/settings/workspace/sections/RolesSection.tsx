import { useState } from "react";
import { useCan, useCreate, useUpdate } from "@refinedev/core";
import { useWorkspaceCustom, useWorkspaceList } from "../../../../hooks/useWorkspaceQuery";

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
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ReadError } from "@/components/ui";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Check, ChevronDown, Pencil, Plus } from "lucide-react";
import type { Role } from "@/types";
import { roleCapNotice } from "@/pages/role-picker-cap";

type CatalogResponse = { catalog: string[]; permissions: string[] };

// parse_query's max_limit: ask for one full page so the server order is
// complete. A workspace past this is reported as truncated below the list.
const ROLES_PAGE_SIZE = 100;

function splitPermission(p: string): [string, string] {
  const i = p.indexOf(":");
  return i < 0 ? [p, ""] : [p.slice(0, i), p.slice(i + 1)];
}

/** Union of scopes across the catalog, in first-seen order. */
function scopeColumns(catalog: string[]): string[] {
  const scopes: string[] = [];
  for (const p of catalog) {
    const [, scope] = splitPermission(p);
    if (scope && !scopes.includes(scope)) scopes.push(scope);
  }
  return scopes;
}

function categoryRows(catalog: string[]): string[] {
  const cats: string[] = [];
  for (const p of catalog) {
    const [cat] = splitPermission(p);
    if (!cats.includes(cat)) cats.push(cat);
  }
  return cats;
}

function PermissionMatrix({
  catalog,
  granted,
}: {
  catalog: string[];
  granted: Set<string>;
}) {
  const scopes = scopeColumns(catalog);
  const categories = categoryRows(catalog);
  const defined = new Set(catalog);
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Category</TableHead>
          {scopes.map((s) => (
            <TableHead key={s} className="text-center">
              {s}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {categories.map((cat) => (
          <TableRow key={cat}>
            <TableCell className="font-medium">{cat}</TableCell>
            {scopes.map((scope) => {
              const perm = `${cat}:${scope}`;
              if (!defined.has(perm)) return <TableCell key={scope} />;
              return (
                <TableCell key={scope} className="text-center">
                  {granted.has(perm) && <Check className="mx-auto h-4 w-4" />}
                </TableCell>
              );
            })}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function PermissionPicker({
  catalog,
  assignable,
  selected,
  onToggle,
}: {
  catalog: string[];
  assignable: string[];
  selected: string[];
  onToggle: (p: string) => void;
}) {
  const scopes = scopeColumns(catalog);
  const categories = categoryRows(catalog);
  const defined = new Set(catalog);
  const allowed = new Set(assignable);
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Category</TableHead>
          {scopes.map((s) => (
            <TableHead key={s} className="text-center">
              {s}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {categories.map((cat) => (
          <TableRow key={cat}>
            <TableCell className="font-medium">{cat}</TableCell>
            {scopes.map((scope) => {
              const perm = `${cat}:${scope}`;
              if (!defined.has(perm)) return <TableCell key={scope} />;
              const enabled = allowed.has(perm);
              return (
                <TableCell key={scope} className="text-center">
                  <Checkbox
                    checked={selected.includes(perm)}
                    disabled={!enabled}
                    onCheckedChange={() => enabled && onToggle(perm)}
                    aria-label={perm}
                  />
                </TableCell>
              );
            })}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function RolesSection() {
  const { result, query } = useWorkspaceList<Role>({
    resource: "roles",
    pagination: { currentPage: 1, pageSize: ROLES_PAGE_SIZE },
  });
  const { result: catalogResult, query: catalogQuery } = useWorkspaceCustom<CatalogResponse>({
    url: "roles/permission-catalog",
    method: "get",
  });
  const catalog = catalogResult?.data?.catalog ?? [];
  const assignable = catalogResult?.data?.permissions ?? [];

  const { mutate: createRole, mutation: createMutation } = useCreate();
  const { mutate: updateRole, mutation: updateMutation } = useUpdate();
  const { data: canManage } = useCan({ resource: "roles", action: "create" });
  const { data: canEdit } = useCan({ resource: "roles", action: "edit" });

  // Ordered by the endpoint (system roles first), so no client sort.
  const rows = result?.data ?? [];
  const total = result?.total ?? rows.length;
  const capNotice = roleCapNotice(rows.length, total);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [permissions, setPermissions] = useState<string[]>([]);
  const [editing, setEditing] = useState<Role | null>(null);

  const toggleExpanded = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const togglePermission = (p: string) =>
    setPermissions((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));

  const clearForm = () => {
    setName("");
    setDescription("");
    setPermissions([]);
  };

  const resetCreate = () => {
    setCreateOpen(false);
    clearForm();
  };

  const submitCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    createRole(
      {
        resource: "roles",
        values: { name, description: description || undefined, permissions },
        successNotification: { message: "Role created", type: "success" },
      },
      { onSuccess: resetCreate },
    );
  };

  const openEdit = (role: Role) => {
    setEditing(role);
    setName(role.name);
    setDescription(role.description ?? "");
    setPermissions([...role.permissions]);
  };

  const closeEdit = () => {
    setEditing(null);
    clearForm();
  };

  const submitEdit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editing || !name.trim()) return;
    updateRole(
      {
        resource: "roles",
        id: editing.id,
        values: { name, description: description || undefined, permissions },
        successNotification: { message: "Role updated", type: "success" },
      },
      { onSuccess: closeEdit },
    );
  };

  const dialogForm = (mode: "create" | "edit") => (
    <form onSubmit={mode === "create" ? submitCreate : submitEdit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor={`role-name-${mode}`}>Name</Label>
        <Input
          id={`role-name-${mode}`}
          placeholder="operator"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor={`role-desc-${mode}`}>Description</Label>
        <Input id={`role-desc-${mode}`} value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>
      <div className="flex flex-col gap-2">
        <Label>Permissions</Label>
        <div className="max-h-80 overflow-y-auto rounded border">
          <PermissionPicker
            catalog={catalog}
            assignable={assignable}
            selected={permissions}
            onToggle={togglePermission}
          />
        </div>
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={mode === "create" ? resetCreate : closeEdit}>
          Cancel
        </Button>
        <Button
          type="submit"
          disabled={mode === "create" ? createMutation.isPending : updateMutation.isPending}
        >
          {mode === "create"
            ? createMutation.isPending
              ? "Creating…"
              : "Create"
            : updateMutation.isPending
              ? "Saving…"
              : "Save"}
        </Button>
      </DialogFooter>
    </form>
  );

  return (
    <div className="flex flex-col gap-4">
      <ReadError error={query.error ?? catalogQuery.error} className="p-0" />
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>Roles</CardTitle>
            <CardDescription>Workspace roles and their permissions.</CardDescription>
          </div>
          <Dialog
            open={createOpen}
            onOpenChange={(open) => (open ? setCreateOpen(true) : resetCreate())}
          >
            <DialogTrigger asChild>
              <Button disabled={!canManage?.can}>
                <Plus className="mr-2 h-4 w-4" />
                New role
              </Button>
            </DialogTrigger>
            <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-2xl">
              <DialogHeader>
                <DialogTitle>Create role</DialogTitle>
                <DialogDescription>Choose a name and the permissions it grants.</DialogDescription>
              </DialogHeader>
              {dialogForm("create")}
            </DialogContent>
          </Dialog>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {capNotice && <p className="text-muted-foreground text-sm">{capNotice}</p>}
          {rows.map((role) => {
            const isOpen = expanded.has(role.id);
            const granted = new Set(role.permissions.includes("*") ? catalog : role.permissions);
            const isOwner = role.name === "owner";
            return (
              <div key={role.id} className="border-border flex flex-col gap-2 rounded-lg border p-4">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => toggleExpanded(role.id)}
                    className="flex items-center gap-2 font-semibold hover:underline"
                    aria-expanded={isOpen}
                  >
                    <ChevronDown
                      className={`h-4 w-4 transition-transform ${isOpen ? "" : "-rotate-90"}`}
                    />
                    {role.name}
                  </button>
                  {role.system && (
                    <Badge variant="secondary" className="text-xs">
                      system
                    </Badge>
                  )}
                  {!isOwner && canEdit?.can && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto"
                      onClick={() => openEdit(role)}
                      aria-label={`Edit ${role.name}`}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                  )}
                </div>
                {role.description && <p className="text-muted-foreground text-sm">{role.description}</p>}
                {isOpen &&
                  (role.permissions.length === 0 ? (
                    <span className="text-muted-foreground text-xs">no permissions</span>
                  ) : (
                    <div className="overflow-x-auto">
                      <PermissionMatrix catalog={catalog} granted={granted} />
                    </div>
                  ))}
              </div>
            );
          })}
          {rows.length === 0 && (
            <p className="text-muted-foreground py-4 text-center text-sm">No roles yet.</p>
          )}
        </CardContent>
      </Card>

      <Dialog open={editing !== null} onOpenChange={(open) => !open && closeEdit()}>
        <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit role</DialogTitle>
            <DialogDescription>Change the name, description, or permissions.</DialogDescription>
          </DialogHeader>
          {dialogForm("edit")}
        </DialogContent>
      </Dialog>
    </div>
  );
}
