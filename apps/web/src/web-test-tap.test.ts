import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
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
  /(^test[-_.]|[-_.]test)\.[cm]?[jt]sx?$|(^|\/)tests?\//.test(path);

test('every tracked web unit test file is covered by the "test" glob', () => {
  const scripts: { test: string } = JSON.parse(
    readFileSync(join(repoRoot, "apps", "web", "package.json"), "utf8"),
  ).scripts;
  const { dir, suffix } = globOf(scripts.test);
  const files = spawnSync("git", ["ls-files", "apps/web"], {
    cwd: repoRoot,
    encoding: "utf8",
  })
    .stdout.split("\n")
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
test("apps/web/web-test.tap is gitignored", () => {
  const check = spawnSync("git", ["check-ignore", "-q", "apps/web/web-test.tap"], { cwd: repoRoot });
  assert.equal(check.status, 0, "add `apps/web/*.tap` to the root .gitignore");
});
