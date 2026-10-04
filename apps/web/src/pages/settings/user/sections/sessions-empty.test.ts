import assert from "node:assert/strict";
import { test } from "node:test";

import { sessionsEmptyMessage } from "./sessions-empty.ts";

test("a settled empty list reads as no sessions", () => {
  assert.equal(sessionsEmptyMessage(0, { isPending: false, isError: false }), "No active sessions.");
});

test("a pending read shows no row, so retries never read as no sessions", () => {
  assert.equal(sessionsEmptyMessage(0, { isPending: true, isError: false }), null);
});

test("a failed read shows the error instead of the empty state", () => {
  const error = { message: "Session store unavailable" };
  assert.equal(sessionsEmptyMessage(0, { isPending: false, isError: true, error }), error.message);
});

test("a failed read without a message still says what failed", () => {
  assert.equal(
    sessionsEmptyMessage(0, { isPending: false, isError: true }),
    "Could not load sessions.",
  );
});

test("a listed session renders no empty row", () => {
  assert.equal(sessionsEmptyMessage(1, { isPending: false, isError: false }), null);
});