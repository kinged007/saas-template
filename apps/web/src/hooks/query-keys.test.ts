import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

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

test("useProfile refreshes identity through the [\"auth\"] prefix on both update paths", () => {
  const source = read("hooks/useProfile.ts");
  const invalidatesAuth = source.match(/invalidateQueries\(\{\s*queryKey:\s*\[\s*"auth"\s*\]\s*\}\)/g) ?? [];
  assert.equal(invalidatesAuth.length, 2, "one per update path: update() and updateAsync()");
  assert.ok(
    IDENTITY_KEY.test(read("contexts/WorkspaceContext.tsx")),
    "the identity query is registered as [\"auth\", \"identity\"], which the [\"auth\"] invalidation prefix-matches",
  );
});
