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
 * Discloses that the picker offers less than the whole workspace; null while the
 * page is complete. The /members endpoint caps the page at its own max_limit, so
 * a workspace past that cap leaves the picker short and nothing else on the
 * section says so. Same wording as the role pickers, so the cap reads the same
 * on both surfaces. `pickable` is the workspace total minus the ineligible rows
 * this page holds; a missing `X-Total-Count` falls back to the page length, so
 * the gate closes on its own, and a stale total below the rows floors at 0
 * rather than going negative. The tail's statuses are unknown, so the
 * denominator counts members, not eligible ones, and it overstates the
 * transferable population whenever an ineligible member sits past the cap. The
 * gate is sound either way: truncation is always disclosed.
 */
export const transferCapNotice = (total: number, members: Member[]): string | null => {
  const eligible = transferEligibleMembers(members);
  const pickable = Math.max(0, total - (members.length - eligible.length));
  return pickable > eligible.length ? `Showing ${eligible.length} of ${pickable} members.` : null;
};

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
    return `No eligible members in the ${loaded} members loaded here. The other ${total - loaded} are not listed, so this workspace may still have an owner to transfer to.`;
  }
  return "No eligible members to transfer to. Transferring needs another active member in this workspace — invite one first.";
};
