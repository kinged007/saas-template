import type { AdminUser } from "@/types";

export type AdminUserDetail = AdminUser & Required<Pick<AdminUser, "workspaces">>;

export const PAGE_SIZE = 20;

/**
 * Patch payload for the disable/re-enable toggle. `errorNotification: false` suppresses
 * refine's generic toast because the caller's `onError` surfaces the server `detail`.
 */
export const adminUserPatch = (user: AdminUser, next: boolean) => ({
  url: `admin/users/${user.id}`,
  method: "patch" as const,
  values: { is_active: next },
  successNotification: {
    message: next ? "Account re-enabled" : "Account disabled",
    type: "success" as const,
  },
  errorNotification: false as const,
});

/** The panel hides the toggle on your own account. UX only — the API rejects self-disable with 409. */
export const canToggleUser = (detail: AdminUserDetail, viewerId?: string | null) =>
  detail.id !== viewerId;

export const asAdminUserDetail = (raw: unknown): AdminUserDetail | undefined => {
  const { id, workspaces } = (raw ?? {}) as Partial<AdminUserDetail>;
  return typeof id === "string" && id.length > 0 && Array.isArray(workspaces)
    ? (raw as AdminUserDetail)
    : undefined;
};

export const pageRange = (current: number, total: number, pageSize = PAGE_SIZE) => {
  const from = total === 0 ? 0 : Math.max(1, Math.min((current - 1) * pageSize + 1, total));
  return {
    from,
    to: total === 0 ? 0 : Math.min(from + pageSize - 1, total),
    totalPages: Math.max(1, Math.ceil(total / pageSize)),
  };
};
