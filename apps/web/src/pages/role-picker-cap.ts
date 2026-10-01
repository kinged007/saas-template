import type { Role } from "../types";
import { isOwnerRoleName } from "./role-name.ts";

// The role pickers on MembersPage offer every role except the owner, so the
// offer and the notice count the same list: a notice counting a role the
// dropdown never lists misreports the cap. The owner is the row
// `is_owner_role_name` locks, so the filter and the notice agree with the
// backend on a row spelled `Owner` as well as on the seeded `owner`.
export const assignableRoles = (roles: Role[]): Role[] =>
  roles.filter((r) => !isOwnerRoleName(r.name));

// The one gate and sentence every role list uses; null while the page is complete.
export const roleCapNotice = (fetched: number, total: number): string | null =>
  total > fetched ? `Showing ${fetched} of ${total} roles.` : null;

// The roles endpoint answers with one capped page, so a workspace past that cap
// leaves both MembersPage pickers short of the full role list. Same wording as
// the roles table in RolesSection, so the cap reads identically on both surfaces.
// `pickable` is the workspace total minus the owner rows this page holds; a
// missing `X-Total-Count` makes the total 0, so it is floored at 0 rather than
// going negative. That total is unknown, so the notice stays suppressed.
export const rolePickerCapNotice = (total: number, roles: Role[]): string | null => {
  const assignable = assignableRoles(roles);
  const pickable = Math.max(0, total - (roles.length - assignable.length));
  return roleCapNotice(assignable.length, pickable);
};