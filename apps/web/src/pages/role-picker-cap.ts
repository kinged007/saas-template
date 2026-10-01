import type { Role } from "../types";

// The role pickers on MembersPage offer every role except the owner, so the
// offer and the notice count the same list: a notice counting a role the
// dropdown never lists misreports the cap.
export const assignableRoles = (roles: Role[]): Role[] => roles.filter((r) => r.name !== "owner");

// The one gate and sentence every role list uses; null while the page is complete.
export const roleCapNotice = (fetched: number, total: number): string | null =>
  total > fetched ? `Showing ${fetched} of ${total} roles.` : null;

// The roles endpoint answers with one capped page, so a workspace past that cap
// leaves both MembersPage pickers short of the full role list.
export const rolePickerCapNotice = (total: number, roles: Role[]): string | null => {
  const assignable = assignableRoles(roles);
  return roleCapNotice(assignable.length, total - (roles.length - assignable.length));
};