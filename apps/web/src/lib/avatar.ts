/**
 * Central avatar helpers – single source of truth for deriving
 * initials / fallback text and normalising avatar URLs.
 *
 * All avatar renderers (Inbox, Members, AppLayout, ComposeDialog, etc.)
 * must use these helpers so display logic stays consistent.
 */

export function getInitials(name: string | null | undefined): string {
  const trimmed = (name ?? "").trim();
  if (!trimmed) return "U";
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }
  return parts[0].slice(0, 2).toUpperCase();
}

/**
 * Derive initials preferring first_name/last_name when available,
 * falling back to a display name or email-derived name.
 * Mirrors the logic previously duplicated across InboxPage.
 */
export function getInitialsFromNames(
  firstName?: string | null,
  lastName?: string | null,
  fallbackName?: string | null,
): string {
  const fn = (firstName ?? "").trim();
  const ln = (lastName ?? "").trim();
  if (fn && ln) return `${fn[0]}${ln[0]}`.toUpperCase();
  if (fn) return fn.slice(0, 2).toUpperCase();
  if (ln) return ln.slice(0, 2).toUpperCase();
  if (fallbackName) return getInitials(fallbackName);
  return "U";
}

/**
 * Normalise an avatar_url value for use as <AvatarImage src>.
 * Returns undefined when the URL is empty/null so Radix falls back.
 */
export function getAvatarSrc(avatarUrl?: string | null): string | undefined {
  const trimmed = (avatarUrl ?? "").trim();
  return trimmed ? trimmed : undefined;
}

/**
 * Convenience helper that returns both src and fallback for a user-like entity.
 * Accepts any object with avatar_url/display_name/first_name/last_name/email.
 */
export function getAvatarData(
  entity: {
    avatar_url?: string | null;
    avatarUrl?: string | null;
    display_name?: string | null;
    displayName?: string | null;
    first_name?: string | null;
    firstName?: string | null;
    last_name?: string | null;
    lastName?: string | null;
    name?: string | null;
    email?: string | null;
  },
  fallbackEmailAsName = true,
): { src: string | undefined; initials: string; name: string } {
  const avatarUrl = entity.avatar_url ?? entity.avatarUrl ?? null;
  const firstName = entity.first_name ?? entity.firstName ?? null;
  const lastName = entity.last_name ?? entity.lastName ?? null;
  const displayName =
    entity.display_name ?? entity.displayName ?? entity.name ?? null;
  let name = (displayName ?? "").trim();
  // If no display name, optionally derive from email prefix
  if (!name && fallbackEmailAsName && entity.email) {
    name = entity.email.split("@")[0] ?? "";
  }
  const initials = getInitialsFromNames(firstName, lastName, name || undefined);
  return { src: getAvatarSrc(avatarUrl), initials, name: name || "U" };
}

export type ParsedAvatar = { kind: "url" | "emoji"; value: string };

export function parseAvatarValue(value?: string | null): ParsedAvatar | null {
  const raw = (value ?? "").trim();
  if (!raw) return null;
  if (raw.startsWith("url:")) return { kind: "url", value: raw.slice(4).trim() };
  if (raw.startsWith("emoji:")) return { kind: "emoji", value: raw.slice(6).trim() };
  if (/^https?:\/\//i.test(raw) || raw.startsWith("data:")) return { kind: "url", value: raw };
  return { kind: "emoji", value: raw };
}

// Backwards-compatible helper for the "user profile class" wording in tasks.
// Allows callers to treat this as UserProfileAvatar.getInitials etc.
export const UserProfileAvatar = {
  getInitials,
  getInitialsFromNames,
  getAvatarSrc,
  getAvatarData,
  parseAvatarValue,
};
