import assert from "node:assert/strict";
import { test } from "node:test";

import { oauthCodeConsumed } from "./oauthCallback.ts";

test("a remount after navigate() stripped the code is a repeat, not a missing code", () => {
  // navigate() rewrites the URL before the remount commits, so the code is
  // already gone from the query string — it was ours, and the sign-in is
  // succeeding. Reporting a missing code here painted a wrong error.
  assert.equal(oauthCodeConsumed(null, "abc123", true), true);
});

test("a remount that still carries the same code is a repeat", () => {
  assert.equal(oauthCodeConsumed("abc123", "abc123", true), true);
});

test("a first visit is never a repeat", () => {
  assert.equal(oauthCodeConsumed(null, null, true), false, "no code and none consumed");
  assert.equal(oauthCodeConsumed(null, null, false), false, "no code, none consumed, signed out");
  assert.equal(oauthCodeConsumed("abc123", null, true), false, "nothing consumed yet");
  assert.equal(oauthCodeConsumed("other", "abc123", true), false, "a different code");
});

test("a stale latch dies with the session it was stored for", () => {
  // The access token is in-memory only: logout and the 401 handler both drop it
  // without clearing `consumedCode`, which is module state and survives a
  // client-side mount. Honouring it then strands the page at "Signing you in…"
  // forever, so a consumed code only counts while the tab still holds the
  // session its exchange stored.
  assert.equal(oauthCodeConsumed(null, "abc123", false), false, "signed out: a fresh missing-code mount");
});