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
