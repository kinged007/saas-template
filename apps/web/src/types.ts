export type Workspace = {
  id: string;
  name: string;
  slug: string;
  description?: string;
  role?: string;
  /** Permissions granted by this user's role in this workspace. */
  permissions?: string[];
  created_by_user_id?: string;
  created_at?: string;
};

export type Identity = {
  id: string;
  email: string;
  display_name: string;
  avatar_url?: string;
  workspaces: Workspace[];
  permissions: string[];
};

export type Role = {
  id: string;
  workspace_id: string;
  name: string;
  description?: string;
  permissions: string[];
  system: boolean;
  created_at?: string;
};

export type Member = {
  id: string;
  email: string;
  display_name: string;
  avatar_url?: string;
  membership_id: string;
  role_id: string;
  role: string;
  status: string;
  joined_at?: string;
};

export type Invitation = {
  id: string;
  workspace_id: string;
  email: string;
  role_id: string;
  invited_by_user_id?: string;
  token: string;
  status: string;
  expires_at?: string;
  accepted_at?: string;
  created_at?: string;
  /** Present on the recipient-facing list: the workspace being joined. */
  workspace_name?: string;
  /** Present on the recipient-facing list: display name of the inviter. */
  invited_by_name?: string;
  /** Pending invitation whose expiry has already passed. */
  expired?: boolean;
};

export type Notification = {
  id: string;
  workspace_id: string;
  workspace_name?: string;
  type: string;
  title: string;
  body?: string;
  payload?: Record<string, unknown>;
  acknowledged: boolean;
  acknowledged_at?: string;
  created_at?: string;
};

export type AuditLogEntry = {
  id: string;
  workspace_id: string;
  actor_user_id?: string | null;
  /** Resolved display name of the actor; absent for system entries. */
  actor_display_name?: string | null;
  resource_type: string;
  resource_id: string;
  action: string;
  details?: Record<string, unknown>;
  ip_address?: string | null;
  created_at?: string;
};
