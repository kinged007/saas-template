import type { Role } from "../types";

// The role pickers on MembersPage offer every role except the owner, so the
// offer and the notice count the same list: a notice counting a role the
// dropdown never lists misreports the cap.
export const assignableRoles = (roles: Role[]): Role[] => roles.filter((r) => r.name !== "owner");

// The roles endpoint answers with one capped page, so a workspace past that cap
// leaves both MembersPage pickers short of the full role list. Same wording as
// the roles table in RolesSection, so the cap reads identically on both surfaces.
export const rolePickerCapNotice = (total: number, roles: Role[]): string | null => {
  const assignable = assignableRoles(roles);
  const pickable = total - (roles.length - assignable.length);
  return pickable > assignable.length ? `Showing ${assignable.length} of ${pickable} roles.` : null;
};