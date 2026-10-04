/**
 * The member a settings section is editing, or null when there is no target.
 *
 * Split out of `useTargetUserId` so the rule is testable without a router:
 * no `:id` is the self page, and your own id is the self page too — the
 * delegated editor manages other members only.
 */
export function resolveTargetUserId(routeId: string | null, identityId?: string): string | null {
  if (!routeId) return null;
  return routeId === identityId ? null : routeId;
}