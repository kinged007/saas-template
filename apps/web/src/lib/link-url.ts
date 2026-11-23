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

// A scheme-less host, which the extension's `defaultProtocol` turns into
// `http://…`: `www.example.com`, `example.com/docs`. No scheme, no leading `//`,
// and a dotted host so a plain word stays a plain word. Start-anchored on
// purpose: safety depends on guard order in `isAllowedLinkHref` — the `@`
// refusal there must run before this test, or `evil.example.com@attacker.com`
// matches on its left half alone.
const BARE_HOST = /^[^\s/?#:@]+\.[^\s/?#:@]+/;
const ANY_SCHEME = /^[a-z][a-z0-9+.-]*:/i;

/**
 * What the editor accepts as a link href, which is `normalizeLinkUrl` plus the
 * bare hosts it autolinks: text typed into the composer arrives without a
 * scheme, and the extension prepends `http://` before storing it, so `www.` and
 * bare domains keep linking the way they did before the allow-list landed.
 * Everything the pre-extension allow-list waved through as a relative href — a
 * word, `/path`, `//host`, any other scheme — is still refused.
 */
export function isAllowedLinkHref(raw: string): boolean {
  const trimmed = raw.trim();
  // `@` separates userinfo from the host, so `https://example.com@attacker.com`
  // resolves to `attacker.com`. No host contains `@`, so the value is refused
  // wherever it appears — before `normalizeLinkUrl`, which would otherwise
  // accept the absolute-URL form.
  if (trimmed.includes("@")) return false;
  if (normalizeLinkUrl(trimmed) !== null) return true;
  if (trimmed.startsWith("//") || ANY_SCHEME.test(trimmed)) return false;
  return BARE_HOST.test(trimmed) && normalizeLinkUrl(`http://${trimmed}`) !== null;
}

// A path inside the app: one leading `/`, never the protocol-relative `//`,
// which is another host.
const SAME_ORIGIN_PATH = /^\/(?!\/)/;

/**
 * Whether an href may sit in the document as written: `isAllowedLinkHref`, plus
 * the two forms pasted rich HTML carries that no absolute http(s) rewrite can
 * produce — a path inside the app and a `mailto:` address. The extension runs
 * its one `isAllowedUri` over every gate (autolink, paste, `parseHTML`,
 * `renderHTML`), so this is the decision the composer hands it and a pasted
 * anchor keeps its mark instead of being silently unlinked. One `isAllowedUri`
 * cannot separate the create paths from `parseHTML`, so the widened set leaks
 * into autolink; the only form that reaches it is `mailto:` (a typed
 * `mailto:a@example.com ` autolinks), which is benign.
 */
export function isAllowedDocumentHref(raw: string): boolean {
  if (isAllowedLinkHref(raw)) return true;
  const trimmed = raw.trim();
  // Whitespace is an injection attempt, and a backslash is a separator a
  // browser reads as `/`, which would turn `/\host` into `//host`.
  if (/[\s\\]/.test(trimmed)) return false;
  if (SAME_ORIGIN_PATH.test(trimmed)) return true;
  try {
    const url = new URL(trimmed);
    return url.protocol === "mailto:" && url.pathname !== "";
  } catch {
    return false;
  }
}
