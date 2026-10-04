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