import assert from "node:assert/strict";
import { test } from "node:test";

import { getDisplayNameFromRow } from "./types.ts";

test("getDisplayNameFromRow prefers first/last name", () => {
  assert.equal(getDisplayNameFromRow({ display_name: "ada", first_name: "Ada", last_name: "Lovelace" }), "Ada L.");
  assert.equal(getDisplayNameFromRow({ display_name: "ada", first_name: "Ada", last_name: null }), "Ada");
  assert.equal(getDisplayNameFromRow({ display_name: "lovelace", first_name: null, last_name: "Lovelace" }), "Lovelace");
});

test("getDisplayNameFromRow collapses a legacy 'First Last' display_name to 'First L.'", () => {
  assert.equal(getDisplayNameFromRow({ display_name: "Ada   Lovelace" }), "Ada L.");
});

test("getDisplayNameFromRow keeps single-word, apostrophe, and empty names as-is", () => {
  assert.equal(getDisplayNameFromRow({ display_name: "O'Brien" }), "O'Brien");
  assert.equal(getDisplayNameFromRow({ display_name: "ada" }), "ada");
  assert.equal(getDisplayNameFromRow({ display_name: "" }), "");
});

test("getDisplayNameFromRow falls back to display_name when names are empty strings", () => {
  assert.equal(getDisplayNameFromRow({ display_name: "ada", first_name: "", last_name: "" }), "ada");
});
