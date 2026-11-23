/**
 * A code this tab already exchanged, stamped with the access token of the
 * session that exchange produced. It is module state, so it outlives the token.
 */
export type ConsumedCode = { code: string; session: string | null };

/**
 * True when this mount of the OAuth callback page is a repeat of a code this
 * tab already exchanged. A remount of the page (StrictMode's dev
 * double-mount, HMR, the workspace provider's loading gate as the identity
 * settles) can land after `navigate()` has rewritten the URL: the
 * code is gone from the query string but it was ours, so the missing-code
 * branch must not report a sign-in that is succeeding.
 *
 * A code still on the URL is always a repeat of the exchange that consumed
 * it, whoever this tab is signed in as now. A missing code is a repeat only
 * for the session the exchange belonged to: `session` is the access token
 * this tab holds now, compared against the latch's own stamp rather than a
 * presence flag, so a sign-out followed by a password sign-in under a
 * different identity does not honour the previous session's latch.
 */
export function oauthCodeConsumed(
  code: string | null,
  consumed: ConsumedCode | null,
  session: string | null,
): boolean {
  if (consumed === null) return false;
  // Same code still on the URL is always a repeat — the exchange for it
  // already happened, whoever this tab is signed in as now.
  if (code !== null) return code === consumed.code;
  return consumed.session === session;
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
