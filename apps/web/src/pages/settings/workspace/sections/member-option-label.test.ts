import assert from "node:assert/strict";
import { test } from "node:test";

import { memberOptionLabel } from "../../../../types.ts";

test("memberOptionLabel composes display name and email", () => {
  const m = {
    first_name: "Ada",
    last_name: "Lovelace",
    email: "ada@example.com",
    display_name: "Ada L.",
  };
  assert.equal(memberOptionLabel(m), "Ada L. (ada@example.com)");
});

test("memberOptionLabel falls back to legacy display_name", () => {
  const m = {
    display_name: "Grace H.",
    first_name: null,
    last_name: null,
    email: "grace@example.com",
  };
  assert.equal(memberOptionLabel(m), "Grace H. (grace@example.com)");
});
