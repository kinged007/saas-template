import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, "dataProvider.ts"), "utf8");

// `adminList` serialises one query parameter per sorter column. A missing
// `field` is skipped, so a bare sort key cannot reach the API; a missing
// `order` must not become `order[]=undefined`, which `QuerySpec.validate_sort`
// answers with 422 ("sort order must be 'asc' or 'desc'"). The API already pads
// an omitted direction with "asc", so leaving the parameter out is the fix.
//
// `node --test` cannot import this module (axios / @refinedev/simple-rest and
// `import.meta.env`), so the loop is pinned by reading the shipped source —
// same approach as resourcePaths.test.ts.
// ponytail: a scan of the source text, not an executed request. Move the
// parameter building into a plain module with no runtime imports when the
// provider grows more query building worth calling directly.
const sorterLoop = source.match(/for \(const s of sorters \?\? \[\]\)[^]*?\n {4}\}/);
assert.ok(sorterLoop, "the adminList sorter loop is gone from dataProvider.ts");

test("adminList skips a sorter without a field", () => {
  assert.match(sorterLoop![0], /if \(!s\.field\) continue;/);
  assert.match(sorterLoop![0], /params\.append\("sort\[\]", s\.field\)/);
});

test("adminList does not append a direction the sorter does not have", () => {
  // `s.order` is `"asc" | "desc"` in refine's CrudSort today, so no app
  // sorter can trip this; the guard is what keeps a future optional or
  // nullable `order` from serialising as `order[]=undefined`.
  assert.match(
    sorterLoop![0],
    /if \(s\.order\) params\.append\("order\[\]", s\.order\);/,
  );
});