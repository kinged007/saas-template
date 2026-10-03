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
