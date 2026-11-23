import { useState } from "react";
import { useCustom, useCustomMutation } from "@refinedev/core";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ListView, ListViewHeader } from "../components/refine-ui/views/list-view";
import { EmptyRow, ReadError, StatusBadge, formatDate } from "../components/ui";
import { invitationStatus, isActionableInvitation } from "./invitation-actions";
import { useWorkspace } from "../contexts/WorkspaceContext";
import { errorMessage } from "@/utils/errorMessage";
import type { Invitation } from "../types";

export function ReceivedInvitationsPage() {
  const { refresh: refreshIdentity } = useWorkspace();
  const { result, query } = useCustom<Invitation[]>({
    url: "invitations/mine",
    method: "get",
  });
  const { mutate: action } = useCustomMutation();
  const [busyId, setBusyId] = useState<string | null>(null);

  const rows = (Array.isArray(result?.data) ? result.data : []) as Invitation[];

  const finish = () => {
    setBusyId(null);
    void query.refetch();
  };

  const accept = (inv: Invitation) => {
    setBusyId(inv.id);
    action(
      {
        url: `invitations/accept?token=${encodeURIComponent(inv.token)}`,
        method: "post",
        values: {},
        errorNotification: false,
      },
      {
        onSuccess: () => {
          toast.success("Invitation accepted", {
            description: `You are now a member of ${inv.workspace_name ?? "the workspace"}.`,
          });
          finish();
          // membership list changed — refresh the identity/workspace switcher
          refreshIdentity();
        },
        onError: (err) => {
          setBusyId(null);
          toast.error("Could not accept invitation", {
            description: errorMessage(err),
          });
          void query.refetch();
        },
      },
    );
  };

  const decline = (inv: Invitation) => {
    setBusyId(inv.id);
    action(
      {
        url: `invitations/${inv.id}/decline`,
        method: "post",
        values: {},
        errorNotification: false,
      },
      {
        onSuccess: () => {
          toast.success("Invitation declined", {
            description: `You declined the invite to ${inv.workspace_name ?? "the workspace"}.`,
          });
          finish();
        },
        onError: (err) => {
          setBusyId(null);
          toast.error("Could not decline invitation", {
            description: errorMessage(err),
          });
          void query.refetch();
        },
      },
    );
  };

  return (
    <ListView>
      <ListViewHeader title="Invitations" canCreate={false} />
      <ReadError error={query.error} className="p-0" />
      <div className="border-border overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Workspace</TableHead>
              <TableHead>Invited by</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Expires</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((inv) => {
              const actionable = isActionableInvitation(inv);
              return (
                <TableRow key={inv.id}>
                  <TableCell className="font-medium">{inv.workspace_name ?? "—"}</TableCell>
                  <TableCell>{inv.invited_by_name ?? "—"}</TableCell>
                  <TableCell>
                    <StatusBadge status={invitationStatus(inv)} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">{formatDate(inv.expires_at)}</TableCell>
                  <TableCell className="text-right">
                    {actionable ? (
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          disabled={busyId === inv.id}
                          onClick={() => accept(inv)}
                        >
                          Accept
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busyId === inv.id}
                          onClick={() => decline(inv)}
                        >
                          Decline
                        </Button>
                      </div>
                    ) : inv.expired ? (
                      <span className="text-muted-foreground text-xs">
                        Expired — ask the workspace owner to re-send.
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
            {rows.length === 0 && <EmptyRow colSpan={5}>No invitations received.</EmptyRow>}
          </TableBody>
        </Table>
      </div>
    </ListView>
  );
}
