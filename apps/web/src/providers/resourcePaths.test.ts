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
});

test("a resource that is its own path is left alone", () => {
  assert.equal(resourcePath("members"), "members");
});

test("only a resource with no GET-by-id route is refused by getOne", () => {
  // The webhooks router serves GET /subscriptions but no GET /subscriptions/{id},
  // so getOne there answers 405. Every other renamed resource has a read-by-id
  // route (`admin-users` → GET /admin/users/{id}).
  assert.equal(hasReadById("webhooks"), false);
  for (const resource of ["admin-users", "members"]) {
    assert.equal(hasReadById(resource), true, resource);
  }
});

test("every read verb in dataProvider maps the resource through resourcePath()", () => {
  const source = readFileSync(join(srcDir, "providers", "dataProvider.ts"), "utf8");
  // `getMany` is the one that silently regressed: it was left to the
  // ...baseDataProvider spread, which builds `${apiUrl}/${resource}` itself and
  // 404s for every renamed resource.
  for (const verb of ["getList", "getOne", "getMany", "update", "create", "deleteOne"]) {
    assert.match(
      source,
      new RegExp(`${verb}:\\s*(?:async\\s*)?\\(\\{[\\s\\S]{0,300}?resourcePath\\(`),
      `dataProvider.${verb} does not route through resourcePath()`,
    );
  }
});