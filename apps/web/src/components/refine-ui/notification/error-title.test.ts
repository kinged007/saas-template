import assert from "node:assert/strict";
import test from "node:test";
import { errorTitle } from "./error-title.ts";

test("errorTitle drops a status token that is not an HTTP status", () => {
  assert.equal(errorTitle("Error (status code: undefined)"), "Error");
  assert.equal(errorTitle("Error (status code: 0)"), "Error");
  assert.equal(errorTitle("Error (status code: 999)"), "Error");
});

test("errorTitle keeps a real HTTP status", () => {
  assert.equal(
    errorTitle("Error (status code: 404)"),
    "Error (status code: 404)",
  );
  assert.equal(
    errorTitle("Error (status code: 500)"),
    "Error (status code: 500)",
  );
});

test("errorTitle keeps a message without a status suffix", () => {
  assert.equal(errorTitle("Network Error"), "Network Error");
  assert.equal(
    errorTitle("status code: 404 is not a suffix"),
    "status code: 404 is not a suffix",
  );
});

test("errorTitle matches the suffix at the end, parentheses and all", () => {
  assert.equal(
    errorTitle("Validation failed (field: email) (status code: 422)"),
    "Validation failed (field: email) (status code: 422)",
  );
  assert.equal(
    errorTitle("Validation failed (field: email) (status code: undefined)"),
    "Validation failed (field: email)",
  );
  assert.equal(
    errorTitle("Retry (status code: 404) failed (status code: undefined)"),
    "Retry (status code: 404) failed",
  );
});
