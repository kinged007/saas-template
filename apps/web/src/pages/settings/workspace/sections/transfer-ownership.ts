import type { Member } from "@/types";
import { canReceiveOwnership } from "../../../member-actions.ts";

/**
 * Members that can receive ownership: active (the rule `transfer_ownership`
 * enforces server-side, via canReceiveOwnership), and not already the owner.
 * The owner test ignores case, like is_owner_role_name on the API — a workspace
 * created before that check can hold `Owner` beside the seeded `owner`, and
 * offering the current owner there produces a 409 on transfer.
 */
export const transferEligibleMembers = (members: Member[]): Member[] =>
  members.filter((m) => m.role.toLowerCase() !== "owner" && canReceiveOwnership(m));

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
