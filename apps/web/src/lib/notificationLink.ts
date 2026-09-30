import type { Notification } from "../types";

const BASE = "https://notification-link.invalid";

/**
 * `payload.url` is meant as an in-app route. Producers are server-side
 * constants today, but a payload built from request data could carry an
 * absolute or `javascript:` value, and the inbox renders this as an anchor
 * href. Resolve against a sentinel base and keep the result only while it
 * stays on that origin.
 */
export function notificationLinkUrl(n: Notification): string | undefined {
  const raw = (n.payload as Record<string, unknown> | undefined)?.url;
  if (typeof raw !== "string" || raw.trim() === "") return undefined;
  let parsed: URL;
  try {
    parsed = new URL(raw, BASE);
  } catch {
    return undefined;
  }
  if (parsed.origin !== BASE) return undefined;
  return `${parsed.pathname}${parsed.search}${parsed.hash}`;
}
