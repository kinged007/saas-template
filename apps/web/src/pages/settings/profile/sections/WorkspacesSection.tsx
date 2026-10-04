import { useState } from "react";
import { useCustom, useCustomMutation, useGetIdentity, useInvalidate } from "@refinedev/core";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyRow, formatDate } from "@/components/ui";
import { NoWorkspaceCard } from "@/components/NoWorkspaceCard";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import { isOwnerRoleName } from "@/pages/role-name";
import type { Identity, Workspace } from "@/types";

export function WorkspacesSection() {
  const { data: identity } = useGetIdentity<Identity>();
  const { refresh } = useWorkspace();
  const invalidate = useInvalidate();
  const list = useCustom<Workspace[]>({ url: "workspaces", method: "get" });
  const { mutateAsync, mutation } = useCustomMutation();
  const [leaving, setLeaving] = useState<Workspace | null>(null);

  const rows: Workspace[] = Array.isArray(list.result?.data)
    ? (list.result.data as Workspace[])
    : (identity?.workspaces ?? []);

  // An empty table here would say "you are in none of these" about a membership
  // list the user never asked about. Gated on the fetch settling so the pending
  // state keeps the row instead of flashing a call to action.
  if (!list.query.isPending && rows.length === 0) {
    return <NoWorkspaceCard single={identity?.single_workspace === true} />;
  }

  const leave = async () => {
    if (!leaving) return;
    try {
      await (mutateAsync({
        url: `workspaces/${leaving.id}/membership`,
        method: "delete",
        values: {},
        errorNotification: false,
      } as never) as Promise<unknown>);
      toast.success(`Left ${leaving.name}`);
      setLeaving(null);
      // The identity carries the workspace list, the active workspace id and
      // every workspace-scoped permission; without it the switcher and the
      // X-Workspace-ID header keep pointing at the workspace just left.
      refresh();
      invalidate({ resource: "workspaces", invalidates: ["all"] });
      list.query.refetch();
    } catch (e) {
      toast.error((e as Error)?.message ?? "Leave failed");
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>My workspaces</CardTitle>
          <CardDescription>Workspaces you are a member of.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Workspace</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Joined</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((w) => (
                  <TableRow key={w.id}>
                    <TableCell className="font-medium">{w.name}</TableCell>
                    <TableCell>
                      {w.role ? <Badge variant="secondary">{w.role}</Badge> : "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground whitespace-nowrap">
                      {formatDate(w.joined_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      {!isOwnerRoleName(w.role) ? (
                        <Button variant="outline" size="sm" onClick={() => setLeaving(w)}>
                          Leave
                        </Button>
                      ) : (
                        <span className="text-muted-foreground text-xs">Owner cannot leave</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {rows.length === 0 && <EmptyRow colSpan={4}>No workspaces yet.</EmptyRow>}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={leaving !== null} onOpenChange={(open) => !open && setLeaving(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Leave {leaving?.name}?</DialogTitle>
            <DialogDescription>
              You will lose access to this workspace. This cannot be undone except by
              re-invitation.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLeaving(null)}>Cancel</Button>
            <Button variant="destructive" onClick={leave} disabled={mutation.isPending}>
              Leave workspace
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
