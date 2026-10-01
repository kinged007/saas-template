/**
 * The composer's link editor only accepts an absolute http(s) URL. A bare word
 * or a relative path would resolve against the app origin, and any other
 * scheme (`javascript:`, `data:`, `file:`) would put a scheme the user did not
 * intend into the document, so everything but http/https is rejected here
 * rather than at the point of use.
 */
export function normalizeLinkUrl(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  return url.href;
}
