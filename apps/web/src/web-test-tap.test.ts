import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { unlinkSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// The web-test CI job tees its TAP output to apps/web/web-test.tap, so the same
// snippet run locally must not leave an untracked file behind.
const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const artifact = "apps/web/web-test.tap";
// Not the CI artifact: the web-test job holds web-test.tap open in tee while
// these tests run, and truncating or unlinking it there would break the job.
const fixture = "apps/web/web-test-tap-guard.tap";

// git exits 0-127 with an answer, 128 and above when it cannot run the command
// at all (no work tree, not a repository); a killed child gives status null.
function git(args: string[]) {
  const run = spawnSync("git", args, { cwd: repoRoot });
  assert.equal(run.error, undefined, `git could not be run: ${run.error?.message}`);
  assert.ok(
    run.status !== null && run.status < 128,
    `git ${args[0]} exited ${run.status} (environment error, git could not answer)`,
  );
  return run;
}

test("apps/web/web-test.tap is gitignored", () => {
  const check = git(["check-ignore", "-q", artifact]);
  assert.equal(
    check.status,
    0,
    `git check-ignore exited ${check.status} (expected 0); is apps/web/*.tap in the root .gitignore?`,
  );
});

test("a .tap file under apps/web stays out of git status", () => {
  writeFileSync(join(repoRoot, fixture), "");
  try {
    // --untracked-files=all overrides a status.showUntrackedFiles=no gitconfig,
    // which would otherwise make this pass with the ignore rule deleted.
    const status = git(["status", "--porcelain", "--untracked-files=all", "--", fixture]);
    assert.equal(status.stdout.toString(), "", `${fixture} shows as untracked`);
  } finally {
    unlinkSync(join(repoRoot, fixture));
  }
});
