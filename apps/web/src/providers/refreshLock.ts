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
 * The Web Locks API serialises the exchange across tabs of one origin, and the
 * late tab then sends the cookie the winner already replaced. It is
 * cross-context (not just cross-tab) and is released when a tab dies, which a
 * promise guard does not give us. Browsers without it fall back to running
 * unguarded, exactly as before.
 */

const REFRESH_LOCK = "saas-template:auth-refresh";

export function hasRefreshLock(): boolean {
  return typeof navigator !== "undefined" && typeof navigator.locks?.request === "function";
}

/** Run `fn` exclusively; concurrent callers queue and run in order. */
export function withRefreshLock<T>(fn: () => Promise<T>): Promise<T> {
  if (!hasRefreshLock()) return fn();
  return navigator.locks.request(REFRESH_LOCK, { mode: "exclusive" }, () => fn());
}
