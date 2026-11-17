/**
 * What the sessions table's single empty row should read.
 *
 * Split out of `SecuritySection` so it is testable: the section is `.tsx`, and
 * `node --test` cannot load one. `null` means the row is not rendered at all.
 */
export function sessionsEmptyMessage(
  count: number,
  query: { isPending: boolean; isError: boolean; error?: { message?: string } | null },
): string | null {
  // A read that has not settled yet must not read as "no sessions": while
  // react-query is still retrying, `result` is undefined, which is the same
  // shape as an empty list.
  if (count > 0 || query.isPending) return null;
  return query.isError ? (query.error?.message ?? "Could not load sessions.") : "No active sessions.";
}
