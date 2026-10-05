import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { hasReadById, resourcePath } from "./resourcePaths.ts";

const srcDir = join(dirname(fileURLToPath(import.meta.url)), "..");

test("a resource whose name differs from its backend path maps onto the path", () => {
  assert.equal(resourcePath("webhooks"), "webhooks/subscriptions");
  assert.equal(resourcePath("admin-users"), "admin/users");
  assert.equal(resourcePath("admin-workspaces"), "admin/workspaces");
  assert.equal(resourcePath("admin-audit"), "admin/audit");
});

test("a resource that is its own path is left alone", () => {
  assert.equal(resourcePath("members"), "members");
});

test("only a resource with no GET-by-id route is refused by getOne", () => {
  // The webhooks router serves GET /subscriptions but no GET /subscriptions/{id}
  // (only PATCH, DELETE, rotate-secret and deliveries), and the admin
  // workspaces/audit lists have no detail route — so getOne there 404s or 405s.
  // Every other renamed resource has a read-by-id route
  // (`admin-users` → GET /admin/users/{id}), and an unmapped resource is
  // assumed to have one.
  for (const resource of ["webhooks", "admin-workspaces", "admin-audit"]) {
    assert.equal(hasReadById(resource), false, resource);
  }
  for (const resource of ["admin-users", "members"]) {
    assert.equal(hasReadById(resource), true, resource);
  }
});

// The verbs that take a `resource` and must send it through resourcePath().
// `getMany` and `deleteMany` are the ones that regressed: they were left to the
// ...baseDataProvider spread, which builds `${apiUrl}/${resource}` itself and
// 404s for every renamed resource (simple-rest v6 does not implement
// `deleteMany` at all, so that verb was not even a function).
const ROUTED_VERBS = [
  "getList",
  "getOne",
  "getMany",
  "create",
  "update",
  "deleteOne",
  "deleteMany",
];

// Verbs whose url does not come from `resource`.
const UNSCOPED_VERBS = ["custom", "getApiUrl"];

test("every resource-scoped verb in dataProvider maps the resource through resourcePath()", () => {
  const source = readFileSync(join(srcDir, "providers", "dataProvider.ts"), "utf8");
  const start = source.indexOf("export const dataProvider");
  const literal = source.slice(start, source.indexOf("\n};", start));
  const declared = [...literal.matchAll(/^ {2}([a-zA-Z]+):/gm)].map((m) => m[1]);

  // The lookahead stops the scan at the next `  verb:` property, so an override
  // that is present but passes the raw resource through still fails.
  for (const verb of ROUTED_VERBS) {
    assert.match(
      literal,
      new RegExp(`${verb}:\\s*(?:async\\s*)?\\(\\{(?:(?!\\n  [a-zA-Z]+:)[\\s\\S])*?resourcePath\\(`),
      `dataProvider.${verb} does not route through resourcePath()`,
    );
  }

  // A verb absent by accident (left to the spread) is indistinguishable from one
  // absent by design when the check is only the loop above, so the declared set
  // is closed: anything new must be routed or explicitly listed as unscoped.
  const routed = new Set([...ROUTED_VERBS, ...UNSCOPED_VERBS]);
  assert.deepEqual(
    declared.filter((verb) => !routed.has(verb)),
    [],
    "dataProvider declares a verb with no entry in ROUTED_VERBS or UNSCOPED_VERBS",
  );
  assert.deepEqual(
    ROUTED_VERBS.filter((verb) => !declared.includes(verb)),
    [],
    "dataProvider is missing an override listed in ROUTED_VERBS",
  );
});