import type { Invitation, InvitationStatus } from "@/types";

type InvitationRow = Pick<Invitation, "status" | "expired">;

/** Delete maps to revoke, so it is offered on a live invitation only. */
export const canRevokeInvitation = (i: InvitationRow) => i.status === "pending";

/**
 * A strict subset of the statuses `WorkspaceService.resend_invitation` in
 * `apps/api/src/services/workspaces.py` will act on: it resets `declined` and
 * `expired` to `pending`, ignores a fresh `pending` row, and rejects the
 * terminal `accepted` and `revoked`. The subset drops the fresh `pending` row,
 * where a re-send is a no-op server-side. Adding a member to `InvitationStatus`
 * without deciding it here is a type error, so a status the API grows later is
 * refused until this table is updated with it.
 */
const RESEND_ALLOWED: Record<InvitationStatus, boolean> = {
  pending: false,
  declined: true,
  accepted: false,
  revoked: false,
  expired: true,
};

export const canResendInvitation = (i: InvitationRow): boolean =>
  i.status === "pending" ? !!i.expired : (RESEND_ALLOWED[i.status] ?? false);

/**
 * Display status. The API flags a pending row past its expiry as `expired`,
 * so a `pending` badge next to a past expiry date reads as still live.
 */
export const invitationStatus = (i: InvitationRow) =>
  i.expired && i.status === "pending" ? "expired" : i.status;
