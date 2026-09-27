import { useState } from "react";
import { useCustom, useCustomMutation } from "@refinedev/core";
import { toast } from "sonner";
import { Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "./ui";
import { useWorkspace } from "../contexts/WorkspaceContext";
import type { Invitation } from "../types";

/**
 * Plain `useCustom`, not the `useWorkspaceQuery` wrappers: those stay disabled
 * until a workspace is selected, and the no-workspace case is the one that
 * needs to see pending invites. `invitations/mine` takes an optional workspace
 * id, so it resolves with none. Both call sites share one cache entry.
 */
export function usePendingInvitations() {
  const { result, query } = useCustom<Invitation[]>({
    url: "invitations/mine",
    method: "get",
  });
  const rows = Array.isArray(result?.data) ? result.data : [];
  const pending = rows.filter((inv) => inv.status === "pending" && !inv.expired);
  return { pending, refetch: query.refetch };
}

export function PendingInvitationsBadge() {
  const { pending } = usePendingInvitations();
  if (pending.length === 0) return null;
  return (
    <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-destructive px-1 text-xs font-medium text-destructive-foreground">
      {pending.length}
    </span>
  );
}

/**
 * Shown where the user has no workspace to select, so an invite can be taken
 * without leaving the create-workspace screen.
 */
export function PendingInvitationsCard() {
  const { refresh: refreshIdentity } = useWorkspace();
  const { pending, refetch } = usePendingInvitations();
  const { mutate: action } = useCustomMutation();
  const [busyId, setBusyId] = useState<string | null>(null);

  const accept = (inv: Invitation) => {
    setBusyId(inv.id);
    action(
      {
        url: `invitations/accept?token=${encodeURIComponent(inv.token)}`,
        method: "post",
        values: {},
      },
      {
        onSuccess: () => {
          toast.success("Invitation accepted", {
            description: `You are now a member of ${inv.workspace_name ?? "the workspace"}.`,
          });
          setBusyId(null);
          void refetch();
          refreshIdentity();
        },
        onError: (err) => {
          setBusyId(null);
          toast.error("Could not accept invitation", {
            description: String((err as { message?: string })?.message ?? err),
          });
          void refetch();
        },
      },
    );
  };

  if (pending.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Mail className="h-4 w-4" />
          You have {pending.length} pending invitation{pending.length > 1 ? "s" : ""}
        </CardTitle>
        <CardDescription>
          Accept one to join a workspace instead of creating a new one.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {pending.map((inv) => (
          <div key={inv.id} className="flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {inv.workspace_name ?? "Workspace"}
              </p>
              <p className="text-muted-foreground truncate text-xs">
                Invited by {inv.invited_by_name ?? "a teammate"}
                {inv.expires_at ? ` — expires ${formatDate(inv.expires_at)}` : ""}
              </p>
            </div>
            <Button
              size="sm"
              disabled={busyId === inv.id}
              onClick={() => accept(inv)}
            >
              Accept
            </Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
