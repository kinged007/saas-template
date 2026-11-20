export type AdminWorkspace = {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  member_count: number;
  created_at?: string;
};

export type AdminWorkspaceMember = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
};

export type AdminWorkspaceDetail = AdminWorkspace & {
  members: AdminWorkspaceMember[];
};

export type WorkspaceEditFields = {
  name: string;
  slug: string;
  description: string;
};

/**
 * Detail guard: every field the inspect panel renders (id, name, slug,
 * members) must clear it, or a payload with no heading renders as broken
 * detail. Mirrors `asAdminUserDetail` in users-toggle.ts.
 */
export function asAdminWorkspaceDetail(raw: unknown): AdminWorkspaceDetail | undefined {
  const w = (raw ?? {}) as Partial<AdminWorkspaceDetail>;
  const valid =
    typeof w.id === "string" &&
    w.id.length > 0 &&
    typeof w.name === "string" &&
    w.name.length > 0 &&
    typeof w.slug === "string" &&
    w.slug.length > 0 &&
    (w.description === undefined || w.description === null || typeof w.description === "string") &&
    Array.isArray(w.members);
  return valid ? (raw as AdminWorkspaceDetail) : undefined;
}

/**
 * Patch payload for the admin workspace edit form. Only changed keys are
 * sent: the API treats a missing key as "no change", so an untouched
 * `null` description must not arrive as `""`. `errorNotification: false`
 * suppresses refine's generic toast because the caller's `onError`
 * surfaces the server `detail`.
 */
export const adminWorkspacePatch = (detail: AdminWorkspaceDetail, fields: WorkspaceEditFields) => {
  const values: Record<string, unknown> = {};
  const name = fields.name.trim();
  const slug = fields.slug.trim();
  if (name !== detail.name) values.name = name;
  if (slug !== detail.slug) values.slug = slug;
  if (fields.description !== (detail.description ?? "")) values.description = fields.description;
  return {
    url: `admin/workspaces/${detail.id}`,
    method: "patch" as const,
    values,
    successNotification: {
      message: "Workspace updated",
      type: "success" as const,
    },
    errorNotification: false as const,
  };
};
