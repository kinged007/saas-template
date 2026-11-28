import { useState } from "react";
import { useCan, useCustomMutation, useDelete, useNavigation } from "@refinedev/core";
import { toast } from "sonner";

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
import { useTargetUserId } from "@/hooks/useProfile";
import { useWorkspaceList } from "../../../../hooks/useWorkspaceQuery";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import { StatusBadge } from "@/components/ui";
import { canReactivateMember, canSuspendMember } from "@/pages/member-actions";
import { isOwnerRoleName } from "@/pages/role-name";
import { getDisplayNameFromRow, type Member } from "@/types";
import { errorMessage } from "@/utils/errorMessage";

type PendingAction = "suspend" | "reactivate" | "reset-mfa" | "remove";

/**
 * Workspace membership moderation for one member. Workspace-scoped like the
 * members list (same `member:update`/`member:delete` gates): suspend and
 * removal need an active manager, MFA reset needs a manager, and the API
 * stays the final authority. Every action confirms first — each one locks
 * someone out or drops a credential.
 */
export function MembershipSection() {
  const userId = useTargetUserId();
  const { workspace } = useWorkspace();
  const { data: canManage } = useCan({ resource: "members", action: "edit" });
  const { data: canRemove } = useCan({ resource: "members", action: "delete" });
  const { result, query } = useWorkspaceList<Member>({
    resource: "members",
    pagination: { pageSize: 100 },
    queryOptions: { enabled: !!workspace && !!userId },
  });
  const { mutate: memberAction, mutation } = useCustomMutation();
  const { mutate: removeMember, mutation: removeMutation } = useDelete();
  const { list } = useNavigation();
  const [confirm, setConfirm] = useState<PendingAction | null>(null);

  const row = result?.data?.find((m) => m.id === userId) ?? null;
  const name = row ? getDisplayNameFromRow(row) : "this member";
  const busy = mutation.isPending || removeMutation.isPending;
  const canModerate = !!canManage?.can;
  const canDelete = !!canRemove?.can;
  const isOwner = !!row && isOwnerRoleName(row.role);

  const refresh = () => {
    void query.refetch();
  };

  const run = (action: PendingAction) => {
    if (!row) return;
    if (action === "remove") {
      removeMember(
        {
          resource: "members",
          id: row.membership_id,
          successNotification: { message: `${name} removed from the workspace`, type: "success" },
          errorNotification: false,
        },
        {
          onSuccess: () => list("members"),
          onError: (err) => toast.error("Could not remove member", { description: errorMessage(err) }),
        },
      );
      return;
    }
    const url =
      action === "reset-mfa"
        ? `members/${row.membership_id}/reset-mfa`
        : `members/${row.membership_id}/${action === "suspend" ? "suspend" : "reactivate"}`;
    const message =
      action === "reset-mfa"
        ? `MFA reset for ${name}`
        : action === "suspend"
          ? `${name} suspended`
          : `${name} reactivated`;
    memberAction(
      {
        url,
        method: "post",
        values: {},
        successNotification: { message, type: "success" },
        errorNotification: false,
      },
      {
        onSuccess: refresh,
        onError: (err: unknown) =>
          toast.error("Action failed", { description: errorMessage(err) }),
      },
    );
  };

  const copy: Record<PendingAction, { title: string; body: string; confirm: string }> = {
    suspend: {
      title: `Suspend ${name}?`,
      body: "They lose access immediately but keep their membership history. You can reactivate them later.",
      confirm: "Suspend",
    },
    reactivate: {
      title: `Reactivate ${name}?`,
      body: "They regain access with their existing role.",
      confirm: "Reactivate",
    },
    "reset-mfa": {
      title: `Reset MFA for ${name}?`,
      body: "Clears their authenticator enrollment. They sign in with their password and enroll again.",
      confirm: "Reset MFA",
    },
    remove: {
      title: `Remove ${name} from this workspace?`,
      body: "They lose access immediately. Their account is kept — this only ends the membership.",
      confirm: "Remove",
    },
  };

  const showSuspend = !!row && canModerate && !isOwner && canSuspendMember(row);
  const showReactivate = !!row && canModerate && canReactivateMember(row);
  const showResetMfa = !!row && canModerate;
  const showRemove = !!row && canDelete && !isOwner;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Membership</CardTitle>
          <CardDescription>
            Moderate this member&apos;s access to {workspace?.name ?? "the workspace"}. Each
            action asks for confirmation first.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {!row && (
            <p className="text-muted-foreground text-sm">
              {query.isPending
                ? "Loading membership…"
                : "No membership found for this member in the active workspace."}
            </p>
          )}
          {row && (
            <>
              <div className="flex items-center gap-3 text-sm">
                <span className="text-muted-foreground">Status</span>
                <StatusBadge status={row.status} />
                {isOwner && (
                  <span className="text-muted-foreground text-xs">
                    The owner cannot be suspended or removed — transfer ownership first.
                  </span>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {showSuspend && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() => setConfirm("suspend")}
                  >
                    Suspend
                  </Button>
                )}
                {showReactivate && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() => setConfirm("reactivate")}
                  >
                    Reactivate
                  </Button>
                )}
                {showResetMfa && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() => setConfirm("reset-mfa")}
                  >
                    Reset MFA
                  </Button>
                )}
                {showRemove && (
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={busy}
                    onClick={() => setConfirm("remove")}
                  >
                    Remove
                  </Button>
                )}
                {!canModerate && !canDelete && (
                  <p className="text-muted-foreground text-sm">
                    You need manager permission to moderate members.
                  </p>
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={confirm !== null} onOpenChange={(open) => { if (!open) setConfirm(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{confirm ? copy[confirm].title : ""}</DialogTitle>
            <DialogDescription>{confirm ? copy[confirm].body : ""}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            <Button
              variant={confirm === "reactivate" ? "default" : "destructive"}
              disabled={busy}
              onClick={() => {
                if (confirm) run(confirm);
                setConfirm(null);
              }}
            >
              {busy ? "Working…" : (confirm ? copy[confirm].confirm : "")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
