/**
 * True when this mount of the OAuth callback page is a repeat of a code this
 * tab already exchanged. The workspace provider unmounts and remounts the page
 * while the identity settles, and that remount can land after `navigate()` has
 * rewritten the URL: the code is gone from the query string but it was ours,
 * so the missing-code branch must not report a sign-in that is succeeding.
 *
 * `sessionAlive` is whether this tab still holds the access token the exchange
 * stored. `consumed` is module state that outlives the token, so a repeat
 * without a session is a stale latch, not a repeat.
 */
export function oauthCodeConsumed(
  code: string | null,
  consumed: string | null,
  sessionAlive: boolean,
): boolean {
  if (consumed === null) return false;
  if (code === null) return sessionAlive;
  return code === consumed;
}

/**
 * Escape target for the callback page's terminal states. The deep-link
 * destination survives in `returnToStore` untouched by this page, so only the
 * current `?error=` needs carrying through — LoginPage renders it back into
 * the same message it shows here.
 */
export function oauthCallbackLoginHref(search: string): string {
  const error = new URLSearchParams(search).get("error");
  return error ? `/login?error=${encodeURIComponent(error)}` : "/login";
}

/** Pending-state budget: past this the page offers the escape instead of hanging. */
export const OAUTH_CALLBACK_TIMEOUT_MS = 15_000;
