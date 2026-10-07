import assert from "node:assert/strict";
import { test } from "node:test";

import { forgotPasswordError } from "./forgot-password.ts";

test("429 maps to the rate-limit message", () => {
  assert.equal(forgotPasswordError(429), "Too many attempts — try again later.");
});

test("every other non-OK status keeps the generic message", () => {
  assert.equal(forgotPasswordError(500), "request failed");
  assert.equal(forgotPasswordError(404), "request failed");
  assert.equal(forgotPasswordError(400), "request failed");
});
