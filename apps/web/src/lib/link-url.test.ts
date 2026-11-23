import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { isAllowedDocumentHref, isAllowedLinkHref, normalizeLinkUrl } from "./link-url.ts";

describe("normalizeLinkUrl", () => {
  it("keeps an absolute https URL and normalises it", () => {
    assert.equal(normalizeLinkUrl("https://example.com"), "https://example.com/");
    assert.equal(normalizeLinkUrl("https://example.com/a?b=1#c"), "https://example.com/a?b=1#c");
  });

  it("keeps an absolute http URL", () => {
    assert.equal(normalizeLinkUrl("http://example.com/x"), "http://example.com/x");
  });

  it("trims surrounding whitespace", () => {
    assert.equal(normalizeLinkUrl("  https://example.com/y  "), "https://example.com/y");
  });

  it("rejects an empty or blank value, so the caller can ask for removal instead", () => {
    assert.equal(normalizeLinkUrl(""), null);
    assert.equal(normalizeLinkUrl("   "), null);
  });

  it("rejects a bare word or a relative path, which would resolve against the app origin", () => {
    assert.equal(normalizeLinkUrl("example.com"), null);
    assert.equal(normalizeLinkUrl("/inbox"), null);
    // The extension's own allow-list accepts this one, resolving it against the app origin.
    assert.equal(normalizeLinkUrl("//evil.example.com"), null);
  });

  it("rejects any scheme other than http and https", () => {
    assert.equal(normalizeLinkUrl("javascript:alert(1)"), null);
    assert.equal(normalizeLinkUrl("JavaScript:alert(1)"), null);
    assert.equal(normalizeLinkUrl("data:text/html,<script>alert(1)</script>"), null);
    assert.equal(normalizeLinkUrl("file:///etc/passwd"), null);
    assert.equal(normalizeLinkUrl("mailto:a@example.com"), null);
  });
});

describe("isAllowedLinkHref", () => {
  it("accepts an absolute http(s) URL", () => {
    assert.equal(isAllowedLinkHref("https://example.com/x"), true);
  });

  it("accepts the scheme-less hosts the extension autolinks to http://", () => {
    assert.equal(isAllowedLinkHref("www.example.com"), true);
    assert.equal(isAllowedLinkHref("example.com"), true);
    assert.equal(isAllowedLinkHref("example.com/docs?a=1"), true);
    assert.equal(isAllowedLinkHref(" example.com "), true);
  });

  it("still refuses a plain word, a relative path and a protocol-relative host", () => {
    // The widening is for bare hosts, not for the relative hrefs that resolve
    // against the app origin.
    assert.equal(isAllowedLinkHref("hello"), false);
    assert.equal(isAllowedLinkHref("/inbox"), false);
    assert.equal(isAllowedLinkHref("//evil.example.com"), false);
    assert.equal(isAllowedLinkHref(""), false);
  });

  it("still refuses every scheme other than http and https", () => {
    assert.equal(isAllowedLinkHref("javascript:alert(1)"), false);
    assert.equal(isAllowedLinkHref("mailto:a@example.com"), false);
    assert.equal(isAllowedLinkHref("data:text/html,<script>alert(1)</script>"), false);
  });

  it("refuses userinfo, so the host a bare host resolves to is never someone else's", () => {
    // `http://evil.example.com@attacker.com` parses — the part before `@` is
    // userinfo and the real host is `attacker.com` — so matching the prefix is
    // approving a link to the attacker's site. No host contains `@`.
    assert.equal(isAllowedLinkHref("evil.example.com@attacker.com"), false);
    assert.equal(isAllowedLinkHref("https://example.com@attacker.com"), false);
    assert.equal(isAllowedLinkHref("http://evil.example.com@attacker.com"), false);
    assert.equal(isAllowedLinkHref("user@example.com"), false);
    assert.equal(isAllowedLinkHref("example.com/a@b"), false);
    assert.equal(isAllowedLinkHref(" example.com@attacker.com "), false);
  });
});

describe("isAllowedDocumentHref", () => {
  it("keeps everything the composer may create", () => {
    assert.equal(isAllowedDocumentHref("https://example.com/x"), true);
    assert.equal(isAllowedDocumentHref("www.example.com"), true);
  });

  it("keeps the relative paths and mailto addresses pasted rich HTML carries", () => {
    // `parseHTML` drops an anchor whose href it refuses, so refusing these
    // here silently unlinks whatever a user pasted from a web page.
    assert.equal(isAllowedDocumentHref("/inbox"), true);
    assert.equal(isAllowedDocumentHref("/inbox?a=1#b"), true);
    assert.equal(isAllowedDocumentHref("mailto:a@example.com"), true);
    assert.equal(isAllowedDocumentHref("mailto:a@example.com?subject=hi"), true);
  });

  it("still refuses every href that is not safe to put in the document", () => {
    assert.equal(isAllowedDocumentHref(""), false);
    assert.equal(isAllowedDocumentHref("//evil.example.com"), false);
    assert.equal(isAllowedDocumentHref("javascript:alert(1)"), false);
    assert.equal(isAllowedDocumentHref("data:text/html,<script>alert(1)</script>"), false);
    assert.equal(isAllowedDocumentHref("file:///etc/passwd"), false);
    assert.equal(isAllowedDocumentHref("mailto:"), false);
    // A newline in an href is a header/attribute injection attempt, and a
    // backslash reads as `/`, so `/\host` is the `//host` case again.
    assert.equal(isAllowedDocumentHref("/inbox\njavascript:alert(1)"), false);
    assert.equal(isAllowedDocumentHref("/\\evil.example.com"), false);
    // The userinfo case from `isAllowedLinkHref` is refused here as well.
    assert.equal(isAllowedDocumentHref("evil.example.com@attacker.com"), false);
  });
});
