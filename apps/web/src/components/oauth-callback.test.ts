import assert from "node:assert/strict";
import { test } from "node:test";

import { oauthCallbackLoginHref, oauthCodeConsumed } from "./oauth-callback.ts";

test("a remount after navigate() stripped the code is a repeat, not a missing code", () => {
  // navigate() rewrites the URL before the remount commits, so the code is
  // already gone from the query string — it was ours, and the sign-in is
  // succeeding. Reporting a missing code here painted a wrong error.
  assert.equal(oauthCodeConsumed(null, { code: "abc123", session: "tok" }, "tok"), true);
});

test("a remount that still carries the same code is a repeat", () => {
  assert.equal(oauthCodeConsumed("abc123", { code: "abc123", session: "tok" }, "tok"), true);
});

test("a remount that still carries the same code is a repeat under any session", () => {
  // The workspace provider's loading gate can remount the page mid-exchange,
  // after the token landed but before the re-stamp runs: the code is still on
  // the URL, so it is a repeat regardless of whose session the tab holds now.
  assert.equal(oauthCodeConsumed("abc123", { code: "abc123", session: "tok" }, "other-token"), true);
});

test("a first visit is never a repeat", () => {
  assert.equal(oauthCodeConsumed(null, null, "tok"), false, "no code and none consumed");
  assert.equal(oauthCodeConsumed(null, null, null), false, "no code, none consumed, signed out");
  assert.equal(oauthCodeConsumed("abc123", null, "tok"), false, "nothing consumed yet");
  assert.equal(oauthCodeConsumed("abc123", null, null), false, "nothing consumed yet, signed out");
});

test("a different code is not a repeat", () => {
  assert.equal(oauthCodeConsumed("other", { code: "abc123", session: "tok" }, "tok"), false);
});

test("the escape link carries the backend error through to /login", () => {
  assert.equal(oauthCallbackLoginHref("?error=sign-in%20failed"), "/login?error=sign-in%20failed");
  assert.equal(
    oauthCallbackLoginHref("?error=registration%20is%20disabled"),
    "/login?error=registration%20is%20disabled",
  );
  assert.equal(oauthCallbackLoginHref("?error=a%26b"), "/login?error=a%26b");
});

test("the escape link is bare /login without an error to carry", () => {
  assert.equal(oauthCallbackLoginHref("?code=abc123"), "/login");
  assert.equal(oauthCallbackLoginHref(""), "/login");
  assert.equal(oauthCallbackLoginHref("?error="), "/login");
});

test("a stale latch dies with the session it was stored for", () => {
  // The access token is in-memory only: logout and the 401 handler both drop it
  // without clearing the latch, which survives a client-side mount. Honouring a
  // latch whose session is gone strands "Signing you in…" on a page nobody left.
  assert.equal(
    oauthCodeConsumed(null, { code: "abc123", session: "tok" }, null),
    false,
    "signed out: a fresh missing-code mount",
  );
});

test("a latch cannot speak for a different signed-in identity", () => {
  // Sign out, then sign in again by password in the same tab: `tokenStore` holds
  // a token again, so a presence check called this session alive. It is not the
  // session the code was exchanged for, and its latch must not stand in for it.
  assert.equal(
    oauthCodeConsumed(null, { code: "abc123", session: "token-a" }, "token-b"),
    false,
    "signed in as someone else: the previous session's latch is not ours",
  );
});
