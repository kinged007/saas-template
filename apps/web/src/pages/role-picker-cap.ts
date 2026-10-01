// The roles endpoint answers with one capped page, so a workspace past that cap
// leaves both MembersPage pickers short of the full role list. Same wording as
// the roles table in RolesSection, so the cap reads identically on both surfaces.
export const rolePickerCapNotice = (
  total: number,
  fetched: number,
): string | null =>
  total > fetched ? `Showing ${fetched} of ${total} roles.` : null;