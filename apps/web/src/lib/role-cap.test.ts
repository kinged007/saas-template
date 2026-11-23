import assert from "node:assert/strict";
import { test } from "node:test";

import { roleCapNotice } from "./role-cap.ts";

// The gate itself: a page short of the total reports the pair, a page that
// covers it reports nothing.
test("a capped page reports fetched of total; a complete page reports nothing", () => {
  assert.equal(roleCapNotice(5, 7), "Showing 5 of 7 roles.");
  assert.equal(roleCapNotice(4, 4), null);
  assert.equal(roleCapNotice(0, 0), null);
  // A total below the fetched count means the count is unusable, not that the
  // page is capped, so it says nothing rather than "Showing 5 of 3 roles."
  assert.equal(roleCapNotice(5, 3), null);
});
