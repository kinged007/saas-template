import { useState } from "react";
import { useCan, useCreate } from "@refinedev/core";
import { useWorkspaceList } from "../hooks/useWorkspaceQuery";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Plus } from "lucide-react";

import { PageHeader } from "../components/refine-ui/layout/page-header";
import { ALL_PERMISSIONS } from "../permissions";
import type { Role } from "../types";

export function RolesPage() {
  const { result } = useWorkspaceList<Role>({ resource: "roles" });
  const { mutate: createRole, mutation } = useCreate();
  const { data: canManage } = useCan({ resource: "roles", action: "create" });

  const rows = result?.data ?? [];
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [permissions, setPermissions] = useState<string[]>([]);

  const togglePermission = (p: string) =>
    setPermissions((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p],
    );

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    createRole(
      {
        resource: "roles",
        values: { name, description: description || undefined, permissions },
        successNotification: { message: "Role created", type: "success" },
      },
      {
        onSuccess: () => {
          setOpen(false);
          setName("");
          setDescription("");
          setPermissions([]);
        },
      },
    );
  };

  const createButton = (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button disabled={!canManage?.can}>
          <Plus className="mr-2 h-4 w-4" />
          New role
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Create role</DialogTitle>
          <DialogDescription>Choose a name and the permissions it grants.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="role-name">Name</Label>
            <Input
              id="role-name"
              placeholder="operator"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="role-desc">Description</Label>
            <Input
              id="role-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label>Permissions</Label>
            <div className="flex max-h-52 flex-col gap-1 overflow-y-auto rounded border p-2">
              {ALL_PERMISSIONS.map((p) => (
                <label key={p} className="flex cursor-pointer items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={permissions.includes(p)}
                    onChange={() => togglePermission(p)}
                    className="size-4 accent-[hsl(var(--primary))]"
                  />
                  {p}
                </label>
              ))}
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Roles" actions={createButton} />
      <div className="flex flex-col gap-3">
        {rows.map((role) => (
          <div key={role.id} className="border-border flex flex-col gap-2 rounded-lg border p-4">
            <div className="flex items-center gap-2">
              <span className="font-semibold">{role.name}</span>
              {role.system && (
                <Badge variant="secondary" className="text-xs">
                  system
                </Badge>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {role.permissions.map((p) => (
                <Badge key={p} variant="outline" className="text-xs">
                  {p}
                </Badge>
              ))}
            </div>
          </div>
        ))}
        {rows.length === 0 && (
          <p className="text-muted-foreground py-4 text-center text-sm">No roles yet.</p>
        )}
      </div>
    </div>
  );
}
