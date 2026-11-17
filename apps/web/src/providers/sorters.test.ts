import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { normalizeSorters } from "./sorters.ts";

test("a sorter without a direction becomes asc, never undefined", () => {
  assert.deepEqual(normalizeSorters([{ field: "name" }]), [
    { field: "name", order: "asc" },
  ]);
  const out = normalizeSorters([{ field: "name" }]);
  assert.ok(!JSON.stringify(out).includes("undefined"));
  // The simple-rest dialect joins directions with commas, so one literal
  // `undefined` entry 422s the whole list on the API's asc|desc check.
  assert.equal(out.map((s) => s.order).join(","), "asc");
});

test("null, undefined and empty directions all degrade to asc", () => {
  assert.deepEqual(
    normalizeSorters([
      { field: "a", order: undefined },
      { field: "b", order: null },
      { field: "c", order: "" },
    ]).map((s) => s.order),
    ["asc", "asc", "asc"],
  );
});

test("a whitespace-only direction degrades to asc like an empty one", () => {
  assert.deepEqual(
    normalizeSorters([
      { field: "a", order: " " },
      { field: "b", order: "\t" },
    ]).map((s) => s.order),
    ["asc", "asc"],
  );
});

test("a real direction keeps only itself, so serialization stays clean", () => {
  const out = normalizeSorters([{ field: "a", order: " desc " }]);
  assert.equal(out[0].order, "desc");
  assert.ok(!JSON.stringify(out).includes(" \""));
});

test("defined directions pass through and stay on their own column", () => {
  const out = normalizeSorters([
    { field: "a", order: "desc" },
    { field: "b" },
    { field: "c", order: "desc" },
  ]);
  assert.deepEqual(
    out.map((s) => [s.field, s.order]),
    [
      ["a", "desc"],
      ["b", "asc"],
      ["c", "desc"],
    ],
  );
});

test("missing input means no sort, and the input is never mutated", () => {
  assert.deepEqual(normalizeSorters(undefined), []);
  assert.deepEqual(normalizeSorters([]), []);
  const input = [{ field: "name" }];
  normalizeSorters(input);
  assert.deepEqual(input, [{ field: "name" }]);
});

test("dataProvider routes the non-admin getList sorters through the normaliser", () => {
  // `node --test` cannot load dataProvider.ts (runtime imports of axios /
  // simple-rest plus `import.meta.env`), so the wiring itself is pinned by
  // scanning the source — same precedent as the retry-override scan in
  // queryClient.test.ts.
  const src = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "dataProvider.ts"),
    "utf8",
  );
  assert.match(src, /normalizeSorters\(params\.sorters\)/);
});
