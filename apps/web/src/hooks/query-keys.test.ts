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

test("countAuthInvalidations spans an option value that itself contains braces (#1646)", () => {
  // A block-bodied option (a `predicate`) puts a second `{ ... }` between
  // invalidateQueries(...)'s braces. A flat `[^{}]` scan splits the call and
  // misses the key; the count must still see the single nested `["auth"]`.
  const region =
    'queryClient.invalidateQueries({ queryKey: ["auth"], predicate: (q) => { return q.queryKey[0] === "auth"; } });';
  assert.equal(countAuthInvalidations(region), 1);
});

test("countAuthInvalidations counts one flat call and rejects a longer key prefix", () => {
  assert.equal(
    countAuthInvalidations('invalidateQueries({ queryKey: ["auth"] });'),
    1,
    'exact ["auth"] key counts',
  );
  assert.equal(
    countAuthInvalidations(
      'invalidateQueries({ queryKey: ["auth", "identity"] });',
    ),
    0,
    "a longer key that only shares the prefix does not count",
  );
  assert.equal(
    countAuthInvalidations(
      'invalidateQueries({ refetchType: "active", queryKey: ["auth"] });',
    ),
    1,
    "flat options around the key do not break the count",
  );
});

// #1547: useUpdateProfileWindow ends the window at `/^export /m`. The real
// follower is an `export function`; pin that the anchor also stops at every
// other export form so a narrower future anchor (functions only) fails here.
const useUpdateProfileHook =
  "export function useUpdateProfile() {\n  return null;\n}\n";
const endAnchorFollowers: [string, string][] = [
  ["type export", "export type Opts = { a: number };\n"],
  ["default export", "export default function fallback() {}\n"],
  ["plain const export", "export const helper = 1;\n"],
];
for (const [name, follower] of endAnchorFollowers) {
  test(`useUpdateProfileWindow stops before an ${name} follower (#1547)`, () => {
    const region = useUpdateProfileWindow(useUpdateProfileHook + follower);
    assert.ok(region !== null, "useUpdateProfile body found");
    assert.ok(
      region.includes("export function useUpdateProfile"),
      "window starts at the hook",
    );
    assert.ok(
      !region.includes(follower),
      `window excludes the ${name} follower`,
    );
  });
}
