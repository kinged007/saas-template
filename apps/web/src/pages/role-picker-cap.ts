import type { Role } from "../types";

// The role pickers on MembersPage offer every role except the owner, so the
// offer and the notice count the same list: a notice counting a role the
// dropdown never lists misreports the cap. Owner is matched case-insensitively
// because the backend does: `is_owner_role_name` locks the row whose lower-cased
// name is "owner" (workspaces.py) and the roles endpoint ranks on
// `func.lower(Role.name)` (roles.py). A row spelled `Owner` is the locked owner
// role to the API, so it must not be offered either.
export const assignableRoles = (roles: Role[]): Role[] =>
  roles.filter((r) => r.name.toLowerCase() !== "owner");

// The gate and sentence the roles table and the MembersPage pickers both share;
// null while the page is complete.
export const roleCapNotice = (fetched: number, total: number): string | null =>
  total > fetched ? `Showing ${fetched} of ${total} roles.` : null;

// The roles endpoint answers with one capped page, so a workspace past that cap
// leaves both MembersPage pickers short of the full role list. Same wording as
// the roles table in RolesSection, so the cap reads identically on both surfaces.
// `pickable` is the workspace total minus the owner rows this page holds, which
// is the workspace's owner count only because `_ROLE_RANK` ranks every owner row
// at 0, so page 1 holds all of them; a missing `X-Total-Count` makes the total 0,
// so it is floored at 0 rather than going negative. That total is unknown, so
// the notice stays suppressed.
export const rolePickerCapNotice = (total: number, roles: Role[]): string | null => {
  const assignable = assignableRoles(roles);
  const pickable = Math.max(0, total - (roles.length - assignable.length));
  return roleCapNotice(assignable.length, pickable);
};

// The notice is the accessible description of the trigger it annotates, so a
// whitespace-only string has to be no notice at all: `aria-describedby` would
// still resolve to the paragraph and announce an empty description. Call it
// once, where the notice is produced (MembersPage), so the notice and the two
// `aria-describedby` gates read the same value.
export const roleCapNoticeText = (text: string | null): string | null => {
  const trimmed = text?.trim();
  return trimmed ? trimmed : null;
};
