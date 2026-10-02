import type { Member } from "@/types";
import { isOwnerRoleName } from "../../../role-name.ts";

/**
 * Members that can receive ownership: active, and not already the owner.
 *
 * `transfer_ownership` refuses a target that already owns the workspace, and it
 * calls the owner the row whose name folds to `owner` (is_owner_role_name), so
 * the filter folds too — otherwise a legacy `Owner` row is offered as its own
 * target.
 */
export const transferEligibleMembers = (members: Member[]): Member[] =>
  members.filter((m) => !isOwnerRoleName(m.role) && m.status === "active");

/**
 * Resolves the selected membership id against the current candidate list. Returns
 * undefined once the id stops naming a candidate (role change, deactivation or
 * removal on refetch), so the action stays disarmed and sends nothing.
 */
export const resolveTransferTarget = (
  candidates: Member[],
  membershipId: string,
): Member | undefined => candidates.find((m) => m.membership_id === membershipId);
