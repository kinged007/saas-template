import assert from "node:assert/strict";
import { test } from "node:test";

import { errorMessage } from "./errorMessage.ts";

test("errorMessage renders the interceptor's message instead of [object Object]", () => {
  // 409 string detail: normalizeError copies the FastAPI detail onto message.
  assert.equal(
    errorMessage({ message: "You cannot disable your own account" }),
    "You cannot disable your own account",
  );
  // 400 object detail: normalizeError leaves axios's default message in place.
  assert.equal(
    errorMessage({
      message: "Request failed with status code 400",
      response: { data: { detail: { code: "2fa_required" } } },
    }),
    "Request failed with status code 400",
  );
  assert.equal(errorMessage(new Error("kaboom")), "kaboom");
  assert.equal(errorMessage("boom"), "boom");
  assert.equal(errorMessage({}), "Request failed");
  assert.equal(errorMessage(null), "Request failed");
  assert.equal(errorMessage(undefined), "Request failed");
});