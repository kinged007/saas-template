// The gate and sentence the roles table and the MembersPage pickers both share;
// null while the page is complete.
export const roleCapNotice = (fetched: number, total: number): string | null =>
  total > fetched ? `Showing ${fetched} of ${total} roles.` : null;
