import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

// The file set and the reporter both live in the "test" script, so CI calls it
// instead of naming a selection of its own.
test('the web-test CI job runs the "test" script instead of its own glob', () => {
  const ci = readFileSync(join(repoRoot, ".github", "workflows", "ci.yml"), "utf8");
  const job = /(^|\n)  web-test:\n([\s\S]*?)(?=\n  \S|$)/.exec(ci)?.[2] ?? "";
  const steps = job
    .split("\n")
    .filter((line) => !/^\s*#/.test(line))
    .join("\n");
  assert.match(steps, /npm test\b/);
  assert.doesNotMatch(steps, /node --test\b/);
});

const globOf = (script: string): { dir: string; suffix: string } => {
  const glob = /"([^"]*\*[^"]*)"/.exec(script)?.[1];
  assert.ok(glob, `no glob in the test script: ${script}`);
  const basename = glob.slice(glob.lastIndexOf("/") + 1);
  assert.match(basename, /^\*[^/]*$/, `unsupported glob: ${glob}`);
  return { dir: glob.slice(0, glob.indexOf("**")), suffix: basename.slice(1) };
};

// The patterns `node --test` picks up without arguments. A file they match that
// the "test" glob misses runs nowhere, so the run is not the full suite.
const defaultDiscovery = (path: string) =>
  /(^|\/)test[-_.][^/]*\.[cm]?[jt]sx?$|[-_.]test\.[cm]?[jt]sx?$|(^|\/)tests?\//.test(path);

test('every tracked web unit test file is covered by the "test" glob', () => {
  const scripts: { test: string } = JSON.parse(
    readFileSync(join(repoRoot, "apps", "web", "package.json"), "utf8"),
  ).scripts;
  const { dir, suffix } = globOf(scripts.test);
  const files = git(["ls-files", "apps/web"])
    .stdout.toString()
    .split("\n")
    .filter(Boolean);
  const uncovered = files.filter(
    (path) =>
      defaultDiscovery(path) && !(path.startsWith(`apps/web/${dir}`) && path.endsWith(suffix)),
  );
  assert.deepEqual(
    uncovered,
    [],
    `never run by "npm test" or CI: ${uncovered.join(", ")} (widen the glob in apps/web/package.json)`,
  );
});

// The web-test CI job tees its TAP output to apps/web/web-test.tap, so the same
// snippet run locally must not leave an untracked file behind.
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
