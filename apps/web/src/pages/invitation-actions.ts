import type { Invitation } from "@/types";

type InvitationRow = Pick<Invitation, "status" | "expired">;

/** Delete maps to revoke, so it is offered on a live invitation only. */
export const canRevokeInvitation = (i: InvitationRow) => i.status === "pending";

/**
 * Mirrors the statuses `resend_invitation` will act on: it resets `declined` and
 * `expired` to `pending`, ignores a fresh `pending` row, and rejects the
 * terminal `accepted` and `revoked`. A status the API adds later is refused
 * until this list is updated with it.
 */
export const canResendInvitation = (i: InvitationRow) =>
  i.status === "declined" ||
  i.status === "expired" ||
  (i.status === "pending" && !!i.expired);

/**
 * Display status. The API flags a pending row past its expiry as `expired`,
 * so a `pending` badge next to a past expiry date reads as still live.
 */
export const invitationStatus = (i: InvitationRow) =>
  i.expired && i.status === "pending" ? "expired" : i.status;
