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
  // The admin workspaces/audit lists have no detail route (the admin surface
  // is list-only) — so getOne there 404s. Every other renamed resource has a
  // read-by-id route (`webhooks` → GET /webhooks/subscriptions/{id},
  // `admin-users` → GET /admin/users/{id}), and an unmapped resource is
  // assumed to have one.
  for (const resource of ["admin-workspaces", "admin-audit"]) {
    assert.equal(hasReadById(resource), false, resource);
  }
  for (const resource of ["webhooks", "admin-users", "members"]) {
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

// Verbs whose url does not come from `resource`. Only verbs actually declared
// in the dataProvider literal belong here: `getApiUrl` arrives via the
// ...baseDataProvider spread and was never assertable, so listing it would be
// an entry that can rot silently.
const UNSCOPED_VERBS = ["custom"];

// simple-rest v6's provider type omits createMany and updateMany, so they are
// declared neither in the provider literal nor as overrides — and the API has
// no bulk create/update routes. Recorded so the absence reads as deliberate:
// if the provider starts declaring one, this list must be updated and the verb
// routed or marked unscoped.
const ABSENT_VERBS = ["createMany", "updateMany"];
function providerVerbDeclarations() {
  const source = readFileSync(join(srcDir, "providers", "dataProvider.ts"), "utf8");
  const start = source.indexOf("export const dataProvider");
  const literal = source.slice(start, source.indexOf("\n};", start));
  return {
    source,
    literal,
    declared: [...literal.matchAll(/^ {2}([a-zA-Z]+):/gm)].map((m) => m[1]),
  };
}

test("deleteMany forwards variables and meta through the fan-out", () => {
  const { source } = providerVerbDeclarations();
  assert.match(
    source,
    /deleteMany:[\s\S]*?\{ resource, ids, \.\.\.params \}[\s\S]*?bulkDelete[\s\S]*?\(resourcePath\(resource\), ids, params\)/,
    "deleteMany drops variables/meta — forward them, the API shape decides whether they are used",
  );
  assert.match(
    source,
    /baseDataProvider\.deleteOne<TData>\(\{ resource, id, \.\.\.params \}\)/,
    "bulkDelete drops variables/meta — thread them into each deleteOne",
  );
});

test("verbs recorded as absent stay absent", () => {
  const { declared } = providerVerbDeclarations();
  assert.deepEqual(
    declared.filter((verb) => ABSENT_VERBS.includes(verb)),
    [],
    "dataProvider now declares a verb recorded in ABSENT_VERBS — move it to ROUTED_VERBS or UNSCOPED_VERBS",
  );
});

test("every resource-scoped verb in dataProvider maps the resource through resourcePath()", () => {
  const { literal, declared } = providerVerbDeclarations();

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
  assert.deepEqual(
    UNSCOPED_VERBS.filter((verb) => !declared.includes(verb)),
    [],
    "UNSCOPED_VERBS lists a verb the provider no longer declares",
  );
});
