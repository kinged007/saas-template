/**
 * Pages a capped list spans. An empty total still counts as one page: the list
 * is on page 1 whatever it holds, and a page count of 0 would make "Page n of 0"
 * and a Next that steps past the end.
 */
export const totalPages = (total: number, pageSize: number): number =>
  Math.max(1, Math.ceil(total / pageSize));

/**
 * The page to show instead of `page`, when the list no longer reaches it (rows
 * deleted from another tab). An unknown total — the first render, or the gap
 * while a page change is in flight — leaves the page alone: clamping against it
 * would throw the reader back to page 1 mid-request and strand them there.
 */
export const clampPage = (page: number, total: number, pageSize: number): number => {
  if (total <= 0) return page;
  return Math.min(page, totalPages(total, pageSize));
};
