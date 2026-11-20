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
  // The admin audit list has no detail route (that surface is list-only) —
  // so getOne there 404s. Every other renamed resource has a read-by-id
  // route (`webhooks` → GET /webhooks/subscriptions/{id},
  // `admin-users` → GET /admin/users/{id},
  // `admin-workspaces` → GET /admin/workspaces/{id}), and an unmapped
  // resource is assumed to have one.
  for (const resource of ["admin-audit"]) {
    assert.equal(hasReadById(resource), false, resource);
  }
  for (const resource of ["webhooks", "admin-users", "admin-workspaces", "members"]) {
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
// Declared keys of the provider literal. Matches the enumerated member forms only:
// `verb:`, `"verb":`, `verb(...)` and `"verb"(...)` shorthand methods, each with an
// optional `async` prefix. Assumes alphanumeric member names at exactly
// two-space indentation. Getters/setters (`get x()`, `set x(v)`) and computed
// keys (`["x"]:`) are not matched.
const DECLARED_KEY = /^ {2}(?:async\s+)?(?:(['"])([a-zA-Z]+)\1|([a-zA-Z]+))(?=\s*:|\s*\()/gm;

function providerVerbDeclarations(
  source: string = readFileSync(join(srcDir, "providers", "dataProvider.ts"), "utf8"),
) {
  const start = source.indexOf("export const dataProvider");
  const literal = source.slice(start, source.indexOf("\n};", start));
  const keys = [...literal.matchAll(DECLARED_KEY)];
  const blocks: Record<string, string> = {};
  const declared = keys.map((key, i) => {
    const verb = key[2] ?? key[3];
    const end = i + 1 < keys.length ? keys[i + 1].index! : literal.length;
    blocks[verb] = literal.slice(key.index!, end);
    return verb;
  });
  return { source, literal, declared, blocks };
}

test("the declared-key scan tolerates every function-member form", () => {
  const members = [
    "  deleteMany: ({ resource }) => resource,\n",
    "  deleteMany: async ({ resource }) => resource,\n",
    `  "deleteMany": ({ resource }) => resource,\n`,
    "  deleteMany({ resource }) { return resource; },\n",
    "  async deleteMany({ resource }) { return resource; },\n",
    `  "deleteMany"({ resource }) { return resource; },\n`,
    `  async "deleteMany"({ resource }) { return resource; },\n`,
  ];
  for (const member of members) {
    const { declared, blocks } = providerVerbDeclarations(
      `export const dataProvider = {\n  ...base,\n${member}};\n`,
    );
    assert.deepEqual(declared, ["deleteMany"], member);
    assert.ok(blocks.deleteMany.includes(member.trim()), member);
  }
});

test("the declared-key scan reads only top-level members", () => {
  const { declared } = providerVerbDeclarations(
    `export const dataProvider = {\n  ...base,\n    nested: ({ resource }) => resource,\n  // getList: commented out\n};\n`,
  );
  assert.deepEqual(declared, []);
});

test("each verb is judged by its own override block", () => {
  const { blocks } = providerVerbDeclarations(
    `export const dataProvider = {\n  getMany: ({ resource }) => resource,\n  create: ({ resource }) => ({ resource: resourcePath(resource) }),\n};\n`,
  );
  assert.doesNotMatch(blocks.getMany, /resourcePath\(/);
  assert.match(blocks.create, /resourcePath\(/);
});

test("the deleteMany forwarding scan is scoped to the deleteMany block", () => {
  // The override drops variables/meta, but code after the literal contains
  // every piece of the forwarding chain — an unbounded scan would match it.
  const { blocks } = providerVerbDeclarations(
    `export const dataProvider = {\n  ...base,\n  deleteMany: ({ resource, ids }) => base,\n};\nexport const stray = { resource, ids, ...params };\nbulkDelete(resourcePath(resource), ids, params);\n`,
  );
  assert.doesNotMatch(
    blocks.deleteMany,
    /\{ resource, ids, \.\.\.params \}[\s\S]*?bulkDelete[\s\S]*?\(resourcePath\(resource\), ids, params\)/,
  );
});

test("deleteMany forwards variables and meta through the fan-out", () => {
  const { source, blocks } = providerVerbDeclarations();
  assert.ok(blocks.deleteMany !== undefined, "dataProvider does not declare deleteMany");
  // Matched inside the override block, so the chain cannot be satisfied by
  // unrelated code elsewhere in the file.
  assert.match(
    blocks.deleteMany,
    /\{ resource, ids, \.\.\.params \}[\s\S]*?bulkDelete[\s\S]*?\(resourcePath\(resource\), ids, params\)/,
    "deleteMany drops variables/meta — forward them, the API shape decides whether they are used",
  );
  // Whole-file, unlike the block above: the per-item forwarding lives inside
  // bulkDelete(), which is outside the provider literal the block covers.
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
  const { declared, blocks } = providerVerbDeclarations();

  // Each verb is scanned inside its own override block, so an override that
  // is present but passes the raw resource through still fails.
  for (const verb of ROUTED_VERBS) {
    assert.ok(blocks[verb] !== undefined, `dataProvider does not declare ${verb}`);
    assert.match(
      blocks[verb],
      /resourcePath\(/,
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
