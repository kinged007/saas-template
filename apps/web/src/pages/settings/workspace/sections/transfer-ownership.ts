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
 * Copy shown in place of the select when no loaded member can take ownership.
 * A truncated list must not tell the owner to invite someone: those members
 * exist, they are just outside the loaded window.
 */
export const transferCandidateMessage = ({
  isPending,
  isError,
  error,
  loaded,
  total,
}: {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  loaded: number;
  total: number;
}): string => {
  if (isPending) return "Loading members…";
  if (isError) {
    const detail = (error as { message?: string })?.message;
    return `Could not load members${detail ? `: ${detail}` : ""}. Reload the page to try again.`;
  }
  if (total > loaded) {
    return `No eligible members in the ${loaded} members loaded here. The other ${total - loaded} are not listed, so this workspace may still have an owner to transfer to.`;
  }
  return "No eligible members to transfer to. Transferring needs another active member in this workspace — invite one first.";
};
