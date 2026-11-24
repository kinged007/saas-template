import assert from "node:assert/strict";
import { test } from "node:test";

import { clampPage, totalPages } from "./list-pager.ts";

test("totalPages rounds a partial page up", () => {
  assert.equal(totalPages(100, 100), 1);
  assert.equal(totalPages(101, 100), 2);
  assert.equal(totalPages(250, 100), 3);
});

// An empty or not-yet-loaded total still renders page 1: dividing it away would
// make the pager ask for a page that does not exist and leave "Page n of 0".
test("totalPages keeps one page when the list is empty", () => {
  assert.equal(totalPages(0, 100), 1);
});

test("clampPage walks a page the list no longer reaches back", () => {
  assert.equal(clampPage(3, 250, 100), 3);
  assert.equal(clampPage(3, 200, 100), 2);
  assert.equal(clampPage(3, 40, 100), 1);
});

// The first render and every page change in flight report an unknown total.
// Clamping against it would throw the reader back to page 1 the moment they
// pressed Next, and leave them there.
test("clampPage leaves the page alone while the total is unknown", () => {
  assert.equal(clampPage(2, 0, 100), 2);
});
