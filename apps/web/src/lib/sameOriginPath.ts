const BASE = "https://same-origin.invalid";

/**
 * The path, query and hash of `raw` when it is a plain in-app path on BASE's
 * own origin, otherwise null.
 *
 * Two classes of value only look like one. The protocol-relative spellings
 * `//host/path` and `/\host/path` parse to another origin. The ASCII tab,
 * newline and carriage return that the URL parser strips before it parses the
 * path either parse to another origin (`/\t/host/path` — the strip collapses
 * the two slashes into `//`) or rewrite themselves into a path nobody asked
 * for on ours (`/\thost/path` becomes `/host/path`).
 *
 * Note that parsing to another origin is not the same as navigating there:
 * `navigate()` goes through `history.pushState`, which is same-origin bound, so
 * a browser clamps all of these back onto our own origin as a dead route, with
 * the recorded destination already spent. Rejecting them here means callers get
 * a path they can navigate to without having to know that.
 *
 * `%5C` needs no clause: the parser does not decode it before path parsing, so
 * it stays a path segment.
 *
 * The returned value is the parser's normalisation (dot segments resolved,
 * `\` as separator), not the input echoed back; same-origin either way.
 */
export function sameOriginPath(raw: string): string | null {
  // Stripped rather than merely resolved: the parser silently rewrites such a
  // value into a path the user never asked for, which is already a drop.
  if (/[\t\n\r]/.test(raw)) return null;
  let parsed: URL;
  try {
    parsed = new URL(raw, BASE);
  } catch {
    return null;
  }
  if (parsed.origin !== BASE) return null;
  const out = `${parsed.pathname}${parsed.search}${parsed.hash}`;
  // Dot segments resolve after the origin check, so `/..//evil.example`
  // normalises to a protocol-relative value: not a plain in-app path.
  return out.startsWith("//") ? null : out;
}