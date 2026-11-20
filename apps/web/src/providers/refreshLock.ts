/**
 * Cross-tab half of the refresh single-flight guard.
 *
 * The refresh token is one HttpOnly cookie per origin, shared by every tab of
 * a browser, and the backend rotates it: the first caller to exchange it wins
 * and every later caller is rejected. A tab-scoped promise cannot see that, so
 * two tabs waking together POST the same token and the loser is answered as a
 * replay — which the backend treats as a stolen token and answers by revoking
 * the user's sessions.
 *
 * The Web Locks API serialises the exchange across tabs of one origin, so the
 * late tab sends the cookie the winner already replaced and never presents an
 * already-used token. That is the whole of what it buys: a benign double-refresh
 * is no longer read as a compromise, so the user's other devices keep their
 * sessions.
 *
 * It does NOT keep sibling tabs signed in. Rotation replaces the session row
 * rather than adding to it, every access token carries that row id as `sid`,
 * and the API validates `sid` live on each request (`deps.py`). The losing tab
 * therefore still gets `401 session revoked` and force-logs out. Fixing that
 * needs a rotation grace period, tracked in #924.
 *
 * The lock is cross-context (not just cross-tab) and is released when a tab
 * dies, which a promise guard does not give us. Browsers without it fall back
 * to running unguarded, exactly as before.
 */

const REFRESH_LOCK = "saas-template:auth-refresh";

export function hasRefreshLock(): boolean {
  return typeof navigator !== "undefined" && typeof navigator.locks?.request === "function";
}

/** Run `fn` exclusively; concurrent callers queue and run in order. */
export async function withRefreshLock<T>(fn: () => Promise<T>): Promise<T> {
  if (!hasRefreshLock()) return fn();
  // `navigator.locks.request` is typed as returning the callback's own return
  // type unwrapped, i.e. Promise<Promise<T>>; awaiting flattens it to T.
  return await navigator.locks.request(REFRESH_LOCK, { mode: "exclusive" }, () => fn());
}
