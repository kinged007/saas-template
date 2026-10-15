import type { Notification } from "../types";
import { sameOriginPath } from "./sameOriginPath.ts";

/**
 * `payload.url` is meant as an in-app route. Producers are server-side
 * constants today, but a payload built from request data could carry an
 * absolute or `javascript:` value, and the inbox renders this as an anchor
 * href — so keep it only while it stays on our own origin.
 */
export function notificationLinkUrl(n: Notification): string | undefined {
  const raw = (n.payload as Record<string, unknown> | undefined)?.url;
  if (typeof raw !== "string" || raw.trim() === "") return undefined;
  return sameOriginPath(raw) ?? undefined;
}
