import type { BadgeProps } from "@/components/ui/badge";
import type {
  AdminUserStatus,
  InvitationStatus,
  JobRunStatus,
  MemberStatus,
} from "@/types";

export type StatusBadgeStatus = MemberStatus | InvitationStatus | AdminUserStatus;

/** `default` and `outline` are structural chrome, not status colours. */
export type BadgeVariant = Exclude<
  NonNullable<BadgeProps["variant"]>,
  "default" | "outline"
>;

/**
 * Total on purpose: a status with no variant here is a compile error, so a new
 * API status cannot be added to the union without an explicit mapping. A
 * status the API ships before these types catch up is unknown at runtime
 * instead — both lookups below fall back to `UNKNOWN_VARIANT` for it.
 */
const VARIANTS: Record<StatusBadgeStatus, BadgeVariant> = {
  active: "secondary",
  invited: "secondary",
  suspended: "secondary",
  pending: "warning",
  accepted: "secondary",
  declined: "secondary",
  revoked: "secondary",
  expired: "destructive",
  disabled: "secondary",
};

/**
 * Fallback for a status the maps do not know at runtime. `undefined` would
 * render cva's `default` variant (primary); `secondary` is the neutral chrome
 * an unmapped status wears until the types catch up.
 */
const UNKNOWN_VARIANT: BadgeVariant = "secondary";

export function statusBadgeVariant(status: StatusBadgeStatus): BadgeVariant {
  return VARIANTS[status] ?? UNKNOWN_VARIANT;
}

/** Total for the same reason as `VARIANTS`. */
const JOB_RUN_VARIANTS: Record<JobRunStatus, BadgeVariant> = {
  pending: "warning",
  running: "warning",
  success: "success",
  failed: "destructive",
  timed_out: "destructive",
};

export function jobRunBadgeVariant(status: JobRunStatus): BadgeVariant {
  return JOB_RUN_VARIANTS[status] ?? UNKNOWN_VARIANT;
}
