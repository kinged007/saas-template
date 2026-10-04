import assert from "node:assert/strict";
import { test } from "node:test";

import { oauthCodeConsumed } from "./oauthCallback.ts";

test("a remount after navigate() stripped the code is a repeat, not a missing code", () => {
  // navigate() rewrites the URL before the remount commits, so the code is
  // already gone from the query string — it was ours, and the sign-in is
  // succeeding. Reporting a missing code here painted a wrong error.
  assert.equal(oauthCodeConsumed(null, "abc123"), true);
});

test("a remount that still carries the same code is a repeat", () => {
  assert.equal(oauthCodeConsumed("abc123", "abc123"), true);
});

test("a first visit is never a repeat", () => {
  assert.equal(oauthCodeConsumed(null, null), false, "no code and none consumed");
  assert.equal(oauthCodeConsumed("abc123", null), false, "nothing consumed yet");
  assert.equal(oauthCodeConsumed("other", "abc123"), false, "a different code");
});