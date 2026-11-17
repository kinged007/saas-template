import assert from "node:assert/strict";
import { test } from "node:test";

import { forgotPasswordError } from "./forgot-password.ts";

test("429 maps to the rate-limit message", () => {
  assert.equal(forgotPasswordError(429), "Too many attempts — try again later.");
  assert.equal(forgotPasswordError(429, null), "Too many attempts — try again later.");
  assert.equal(
    forgotPasswordError(429, { headers: { get: () => "not-a-number" } }),
    "Too many attempts — try again later.",
  );
  assert.equal(
    forgotPasswordError(429, { headers: { get: () => "0" } }),
    "Too many attempts — try again later.",
  );
  // header absent maps to exactly 0 seconds, so it lands on the same fallback.
  assert.equal(
    forgotPasswordError(429, { headers: { get: () => null } }),
    "Too many attempts — try again later.",
  );
  assert.equal(
    forgotPasswordError(429, { headers: { get: () => "-5" } }),
    "Too many attempts — try again later.",
  );
  // exactly one minute is still rounded to "~1 min", not bumped to 2.
  assert.equal(
    forgotPasswordError(429, { headers: { get: () => "60" } }),
    "Too many attempts — try again in ~1 min.",
  );
});

test("429 renders whole minutes from the Retry-After header", () => {
  assert.equal(
    forgotPasswordError(429, { headers: { get: () => "120" } }),
    "Too many attempts — try again in ~2 min.",
  );
});

test("429 rounds partial minutes up to at least one", () => {
  assert.equal(
    forgotPasswordError(429, { headers: { get: () => "95" } }),
    "Too many attempts — try again in ~2 min.",
  );
  assert.equal(
    forgotPasswordError(429, { headers: { get: () => "30" } }),
    "Too many attempts — try again in ~1 min.",
  );
});

test("every other non-OK status keeps the generic message", () => {
  assert.equal(forgotPasswordError(500), "request failed");
  assert.equal(forgotPasswordError(404), "request failed");
  assert.equal(forgotPasswordError(400), "request failed");
});
