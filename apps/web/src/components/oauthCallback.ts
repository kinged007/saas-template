/**
 * True when this mount of the OAuth callback page is a repeat of a code this
 * tab already exchanged. The workspace provider unmounts and remounts the page
 * while the identity settles, and that remount can land after `navigate()` has
 * rewritten the URL: the code is gone from the query string but it was ours,
 * so the missing-code branch must not report a sign-in that is succeeding.
 */
export function oauthCodeConsumed(code: string | null, consumed: string | null): boolean {
  return consumed !== null && (code === null || code === consumed);
}