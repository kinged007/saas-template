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

export type UserProfile = {
  id: string;
  user_id: string;
  first_name?: string | null;
  last_name?: string | null;
  bio?: string | null;
  phone_number?: string | null;
  timezone?: string | null;
  locale?: string | null;
  date_of_birth?: string | null;
  website_url?: string | null;
  location?: string | null;
  custom_data: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
} & Record<string, unknown>;

export function getProfileField(
  profile: UserProfile | null | undefined,
  key: string,
  fallback: unknown = null
): unknown {
  if (!profile) return fallback ?? null;
  if (key === "__proto__" || key === "constructor" || key === "prototype") return fallback ?? null;
  const top = (profile as Record<string, unknown>)[key];
  if (top !== undefined) return top;
  if (profile.custom_data && (profile.custom_data as Record<string, unknown>)[key] !== undefined) {
    return (profile.custom_data as Record<string, unknown>)[key];
  }
  return fallback ?? null;
}

export type Identity = {
  id: string;
  email: string;
  display_name: string;
  avatar_url?: string;
  workspaces: Workspace[];
  permissions: string[];
  /** Bootstrap superuser (SUPERADMIN_EMAIL): manages global scheduled jobs. */
  is_superuser?: boolean;
  profile?: UserProfile;
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

export type Conversation = {
  id: string;
  workspace_id: string;
  title: string | null;
  created_by_user_id: string;
  last_message_at: string | null;
  last_message_preview: string | null;
  unread_count: number;
  is_archived: boolean;
  participants: Array<{
    type: "user" | "agent";
    id: string;
    display_name: string;
    avatar_url?: string | null;
  }>;
  message_count?: number;
  created_at: string;
  updated_at: string;
  /** Embedded first message when the conversation was just created */
  first_message?: Message;
};

export type Message = {
  id: string;
  conversation_id: string;
  sender_type: "user" | "agent";
  sender_id: string;
  sender_name: string;
  sender_avatar_url?: string | null;
  body: string;
  body_html?: string | null;
  created_at: string;
  updated_at?: string;
};

export type ApiKey = {
  id: string;
  workspace_id: string;
  name: string;
  /** Display prefix of the secret (e.g. `sk_live_AbCdEfGh`). */
  key_prefix: string;
  permissions: string[];
  created_by_user_id?: string;
  last_used_at?: string;
  revoked_at?: string;
  created_at?: string;
};

/** POST /api-keys response — the raw `key` is only returned once. */
export type ApiKeyCreated = ApiKey & {
  key: string;
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

export type JobParamSpec = {
  type: "int" | "float" | "string" | "password" | "date";
  default?: unknown;
  min?: number;
  max?: number;
  max_length?: number;
  label?: string;
  help?: string;
};

export type ScheduledJob = {
  id: string;
  key: string;
  workspace_id: string | null;
  scope: "workspace" | "global";
  name: string;
  description: string;
  cron_schedule: string;
  params_schema: Record<string, JobParamSpec>;
  params: Record<string, unknown>;
  enabled: boolean;
  missed_policy: "single" | "ignore";
  timeout_seconds: number;
  next_run_at?: string | null;
  last_run_at?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type JobRunStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "timed_out";

export type JobRun = {
  id: string;
  definition_id: string;
  workspace_id: string | null;
  status: JobRunStatus;
  trigger: "scheduled" | "manual";
  actor_user_id?: string | null;
  scheduled_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  error?: string | null;
  params?: Record<string, unknown>;
  created_at?: string;
};

export type JobLogEntry = {
  seq: number;
  ts: string;
  level: string;
  message: string;
};
