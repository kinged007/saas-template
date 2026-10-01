import type { Member } from "@/types";

/** Members that can receive ownership: active, and not already the owner. */
export const transferEligibleMembers = (members: Member[]): Member[] =>
  members.filter((m) => m.role !== "owner" && m.status === "active");

/**
 * Resolves the selected membership id against the current candidate list. Returns
 * undefined once the id stops naming a candidate (role change, deactivation or
 * removal on refetch), so the action stays disarmed and sends nothing.
 */
export const resolveTransferTarget = (
  candidates: Member[],
  membershipId: string,
): Member | undefined => candidates.find((m) => m.membership_id === membershipId);

/**
 * The id the Select stays bound to. A stale id names no item, and an item-less
 * value renders as an empty box rather than the placeholder, so it collapses to
 * "" once the picked member is gone.
 */
export const liveTransferId = (candidates: Member[], membershipId: string): string =>
  resolveTransferTarget(candidates, membershipId) ? membershipId : "";
