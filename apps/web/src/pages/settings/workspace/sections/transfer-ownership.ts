import type { Member } from "@/types";
import { canReceiveOwnership } from "../../../member-actions.ts";
import { isOwnerRoleName } from "../../../role-name.ts";

/**
 * Members that can receive ownership: active (the rule `transfer_ownership`
 * enforces server-side), and not already the owner. The owner half folds too:
 * `transfer_ownership` rejects a target that already owns the workspace and
 * calls the owner the row whose name folds to `owner` (is_owner_role_name), so a
 * legacy `Owner` row is not offered as its own target.
 */
export const transferEligibleMembers = (members: Member[]): Member[] =>
  members.filter((m) => !isOwnerRoleName(m.role) && canReceiveOwnership(m));

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
  loaded,
  total,
}: {
  isPending: boolean;
  isError: boolean;
  loaded: number;
  total: number;
}): string => {
  if (isPending) return "Loading members…";
  // The raw error body stays in the toast; a serialised FastAPI `detail`
  // object is not copy to put in front of the owner.
  if (isError) return "Could not load members. Reload the page to try again.";
  if (total > loaded) {
    return `No eligible members in the ${loaded} members loaded here. The other ${total - loaded} are not listed, so this workspace may still have an owner to transfer to. The list is newest first, so the ones left out are the oldest members.`;
  }
  return "No eligible members to transfer to. Transferring needs another active member in this workspace — invite one first.";
};
