import type { Member, MemberStatus } from "@/types";

type MemberRow = Pick<Member, "status">;

/**
 * A strict subset of the statuses `WorkspaceService.suspend_member` in
 * `apps/api/src/services/workspaces.py` will act on: it suspends any member
 * that is not already `suspended`, and returns an already-suspended one
 * unchanged. The subset drops `suspended`, where a suspend is a no-op
 * server-side. Adding a member to `MemberStatus` without deciding it here is a
 * type error, so a status the API grows later is refused until this table is
 * updated with it.
 */
const SUSPEND_ALLOWED: Record<MemberStatus, boolean> = {
  active: true,
  invited: true,
  suspended: false,
};

/** The inverse: `reactivate_member` rejects with 409 on anything not `suspended`. */
const REACTIVATE_ALLOWED: Record<MemberStatus, boolean> = {
  active: false,
  invited: false,
  suspended: true,
};

export const canSuspendMember = (m: MemberRow): boolean =>
  SUSPEND_ALLOWED[m.status] ?? false;

export const canReactivateMember = (m: MemberRow): boolean =>
  REACTIVATE_ALLOWED[m.status] ?? false;