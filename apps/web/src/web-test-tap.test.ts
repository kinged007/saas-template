import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

// The web-test CI job tees its TAP output to apps/web/web-test.tap, so the same
// snippet run locally must not leave an untracked file behind.
test("apps/web/web-test.tap is gitignored", () => {
  const check = spawnSync("git", ["check-ignore", "-q", "apps/web/web-test.tap"], { cwd: repoRoot });
  assert.equal(check.status, 0, "add `apps/web/*.tap` to the root .gitignore");
});
