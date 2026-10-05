import assert from "node:assert/strict";
import { test } from "node:test";

import { sameOriginPath } from "./sameOriginPath.ts";

test("keeps plain in-app paths", () => {
  assert.equal(sameOriginPath("/api-keys?page=2"), "/api-keys?page=2");
  assert.equal(sameOriginPath("/inbox#x"), "/inbox#x");
  assert.equal(sameOriginPath("/"), "/");
});

test("rejects the spellings that only look like a relative path", () => {
  for (const raw of [
    "//evil.example/x",
    "/\\evil.example/x",
    "/\\\\evil.example/x",
    "/\tevil.example/x",
    "/\t/evil.example/x",
    "\t//evil.example/x",
    "/\nevil.example/x",
    "/\n/evil.example/x",
    "/\revil.example/x",
    "/\r/evil.example/x",
    "/..//evil.example",
    "/.//evil.example",
    "/%2e%2e//evil.example",
    "https://evil.example/x",
    "javascript:alert(1)",
    "http://[",
  ]) {
    assert.equal(sameOriginPath(raw), null, JSON.stringify(raw));
  }
});

test("a percent-encoded backslash stays a path segment", () => {
  assert.equal(sameOriginPath("/%5Cevil.example/x"), "/%5Cevil.example/x");
});