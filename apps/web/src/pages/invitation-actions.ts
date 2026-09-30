import type { Invitation } from "@/types";

type InvitationRow = Pick<Invitation, "status" | "expired">;

/** Delete maps to revoke, so it is offered on a live invitation only. */
export const canRevokeInvitation = (i: InvitationRow) => i.status === "pending";

/**
 * Mirrors the statuses `resend_invitation` will act on: `accepted` and `revoked`
 * are terminal, and a fresh `pending` row is a no-op server-side.
 */
export const canResendInvitation = (i: InvitationRow) =>
  i.status !== "accepted" &&
  i.status !== "revoked" &&
  (i.status !== "pending" || !!i.expired);
