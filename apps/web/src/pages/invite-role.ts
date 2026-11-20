import type { Role } from "@/types";

/**
 * Resolves the picked role id against the list the invite picker offers. Returns
 * undefined once the id stops naming an offered role (a refetch that no longer
 * lists it), so the submit stays blocked and sends nothing.
 */
export const resolveInviteRole = (roles: Role[], roleId: string): Role | undefined =>
  roles.find((r) => r.id === roleId);
