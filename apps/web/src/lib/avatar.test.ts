import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { isStoredFileUrl } from "./avatar.ts";

describe("isStoredFileUrl", () => {
  it("matches the path POST /files returns", () => {
    assert.equal(isStoredFileUrl("/api/v1/files/abc-123", "/api/v1"), true);
  });

  it("matches when the API base is an absolute URL", () => {
    const api = "https://api.example.com/api/v1";
    assert.equal(isStoredFileUrl("/api/v1/files/abc-123", api), true);
    assert.equal(isStoredFileUrl("https://api.example.com/api/v1/files/abc", api), true);
    assert.equal(isStoredFileUrl("https://cdn.example.com/api/v1/files/abc", api), false);
  });

  it("leaves external and non-file URLs alone", () => {
    assert.equal(isStoredFileUrl("https://cdn.example.com/a.png", "/api/v1"), false);
    assert.equal(isStoredFileUrl("data:image/png;base64,AAAA", "/api/v1"), false);
    assert.equal(isStoredFileUrl("/avatars/local.png", "/api/v1"), false);
  });
});