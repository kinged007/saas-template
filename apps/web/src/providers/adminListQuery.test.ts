import assert from "node:assert/strict";
import test from "node:test";

import { adminListQuery } from "./adminListQuery.ts";

// Mirrors `parse_query` (apps/api/src/api/crud.py): `sort[]` and `order[]` are
// paired by position, empty directions are dropped, and missing directions are
// padded with "asc" at the *end* only.
const appliedPairs = (params: URLSearchParams): [string, string][] => {
  const columns = params.getAll("sort[]");
  const orders = params.getAll("order[]").filter((o) => o);
  return columns.map((name, i) => [name, orders[i] ?? "asc"]);
};

test("a sorter without a direction becomes order[]=asc, never order[]=undefined", () => {
  const params = adminListQuery({ sorters: [{ field: "name" }] });
  assert.equal(params.toString(), "offset=0&limit=10&sort%5B%5D=name&order%5B%5D=asc");
  assert.ok(!params.toString().includes("undefined"));
});

test("directions stay on their own column when an earlier sorter has none", () => {
  const withoutMiddle = adminListQuery({
    sorters: [{ field: "name" }, { field: "created_at", order: "desc" }],
  });
  assert.deepEqual(appliedPairs(withoutMiddle), [
    ["name", "asc"],
    ["created_at", "desc"],
  ]);

  const withoutMiddleOfThree = adminListQuery({
    sorters: [
      { field: "a", order: "desc" },
      { field: "b" },
      { field: "c", order: "desc" },
    ],
  });
  assert.deepEqual(appliedPairs(withoutMiddleOfThree), [
    ["a", "desc"],
    ["b", "asc"],
    ["c", "desc"],
  ]);
});

test("an empty direction degrades to asc — the parser drops it just like an omitted one", () => {
  const params = adminListQuery({
    sorters: [{ field: "a" }, { field: "b", order: "" }],
  });
  assert.deepEqual(appliedPairs(params), [
    ["a", "asc"],
    ["b", "asc"],
  ]);
});

test("a sorter without a field is skipped without shifting the other directions", () => {
  const params = adminListQuery({
    sorters: [{ field: "a", order: "desc" }, {}, { field: "b", order: "desc" }],
  });
  assert.deepEqual(appliedPairs(params), [
    ["a", "desc"],
    ["b", "desc"],
  ]);
});

test("pagination becomes offset/limit and q stays a bare cross-field term", () => {
  assert.equal(
    adminListQuery({ currentPage: 3, pageSize: 20 }).toString(),
    "offset=40&limit=20",
  );
  const params = adminListQuery({
    filters: [
      { field: "q", operator: "contains", value: "acme" },
      { field: "status", operator: "eq", value: "active" },
      { operator: "and", value: [] },
    ],
  });
  assert.equal(params.get("q"), "acme");
  assert.equal(params.get("status_like"), "active");
  assert.equal(params.get("and_like"), null);
});