import type { AdminUserDetail } from "./users-toggle";

/**
 * Why the admin user detail panel is empty. `asAdminUserDetail` returns
 * `undefined` for a payload its guard rejects, and a panel that never appears
 * reads as nothing having been wrong.
 */
export function userDetailMessage(
  detail: AdminUserDetail | undefined,
  selected: boolean,
  query: { isPending: boolean },
): string | null {
  if (!selected || detail !== undefined || query.isPending) return null;
  return "User details could not be loaded.";
}
