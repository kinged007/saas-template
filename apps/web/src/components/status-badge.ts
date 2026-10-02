import type { BadgeProps } from "@/components/ui/badge";
import type { AdminUserStatus, InvitationStatus, MemberStatus } from "@/types";

export type StatusBadgeStatus = MemberStatus | InvitationStatus | AdminUserStatus;

type BadgeVariant = NonNullable<BadgeProps["variant"]>;

/**
 * Total on purpose: a status with no variant here is a compile error, so a new
 * API status cannot reach the badge and fall through to `secondary` unnoticed.
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

export function statusBadgeVariant(status: StatusBadgeStatus): BadgeVariant {
  return VARIANTS[status];
}