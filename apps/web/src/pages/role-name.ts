/**
 * Role names reach the browser verbatim, and a workspace created before the
 * case-insensitive name check (#328) can hold `Owner` or `Admin` beside its
 * seeded row. The API matches those the same way we do — `is_owner_role_name`
 * and `is_manager_role_name` in `apps/api/src/services/workspaces.py` fold the
 * case, and the roles list ranks on `func.lower(Role.name)`. Folding here too
 * keeps the UI's offer and the API's refusal on the same row: a control shown
 * for an owner is refused with 409, and one hidden from a manager is refused
 * with 403.
 *
 * The fold is `toLowerCase()` against ASCII literals, deliberately identical to
 * the server's `str.lower()` rather than a locale-aware case map: the two sides
 * have to agree, so change one only together with the other.
 */

export const isOwnerRoleName = (name: string | null | undefined): boolean =>
  (name ?? "").toLowerCase() === "owner";

export const isManagerRoleName = (name: string | null | undefined): boolean => {
  const lowered = (name ?? "").toLowerCase();
  return lowered === "admin" || isOwnerRoleName(lowered);
};
