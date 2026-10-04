/**
 * A code this tab already exchanged, stamped with the access token of the
 * session that exchange produced. It is module state, so it outlives the token.
 */
export type ConsumedCode = { code: string; session: string | null };

/**
 * True when this mount of the OAuth callback page is a repeat of a code this
 * tab already exchanged. The workspace provider unmounts and remounts the page
 * while the identity settles, and that remount can land after `navigate()` has
 * rewritten the URL: the code is gone from the query string but it was ours,
 * so the missing-code branch must not report a sign-in that is succeeding.
 *
 * `session` is the access token this tab holds now, or `null` when signed out.
 * It is compared against the latch's own stamp rather than reduced to a
 * presence flag: a sign-out followed by a password sign-in puts a token back,
 * and only the value tells that session apart from the one the exchange
 * belonged to. A latch stamped for another session is dead — it answers for a
 * session this tab no longer has.
 */
export function oauthCodeConsumed(
  code: string | null,
  consumed: ConsumedCode | null,
  session: string | null,
): boolean {
  if (consumed === null) return false;
  if (consumed.session !== session) return false;
  if (code === null) return true;
  return code === consumed.code;
}