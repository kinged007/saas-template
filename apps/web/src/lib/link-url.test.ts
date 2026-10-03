import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { isAllowedLinkHref, normalizeLinkUrl } from "./link-url.ts";

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
});
