import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { countAuthInvalidations, stripComments, useUpdateProfileWindow } from "./query-keys-guard.ts";

const srcDir = join(dirname(fileURLToPath(import.meta.url)), "..");

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

const read = (rel: string) => readFileSync(join(srcDir, rel), "utf8");

// refine registers the identity query as ["auth", "identity"]; WorkspaceContext
// reads and writes that key directly.
const IDENTITY_KEY = /\[\s*"auth"\s*,\s*"identity"\s*\]/;

test('no source invalidates a "getIdentity" query key the app never registers', () => {
  const hits = sources(srcDir)
    .filter((path) => /queryKey:\s*\[\s*"getIdentity"\s*\]/.test(readFileSync(path, "utf8")))
    .map((path) => path.slice(srcDir.length + 1));
  assert.deepEqual(hits, []);
});

test('useUpdateProfile refreshes identity through the ["auth"] prefix on its update path', () => {
  const source = read("hooks/useProfile.ts");
  // updateAsync was removed as an unused second copy of this topology:
  // update() is the only update path, so pin that it stays that way.
  assert.ok(
    !/\bupdateAsync\b/.test(stripComments(source)),
    "no updateAsync: update() is the only update path",
  );
  // Scope the count to the hook, not the file, so other hooks in this file
  // (e.g. useDeleteAccount) can gain their own invalidations freely.
  const region = useUpdateProfileWindow(source);
  assert.ok(region !== null, "useUpdateProfile body found");
  assert.equal(
    countAuthInvalidations(region),
    1,
    'exactly one ["auth"] invalidation in useUpdateProfile().update()',
  );
  assert.ok(
    IDENTITY_KEY.test(read("contexts/WorkspaceContext.tsx")),
    'the identity query is registered as ["auth", "identity"], which the ["auth"] invalidation prefix-matches',
  );
});
