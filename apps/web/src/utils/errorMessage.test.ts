import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { errorMessage } from "./errorMessage.ts";

test("errorMessage renders the interceptor's message instead of [object Object]", () => {
  // 409 string detail: normalizeError copies the FastAPI detail onto message.
  assert.equal(
    errorMessage({ message: "You cannot disable your own account" }),
    "You cannot disable your own account",
  );
  // 400 object detail: normalizeError leaves axios's default message in place.
  assert.equal(
    errorMessage({
      message: "Request failed with status code 400",
      response: { data: { detail: { code: "2fa_required" } } },
    }),
    "Request failed with status code 400",
  );
  assert.equal(errorMessage(new Error("kaboom")), "kaboom");
  assert.equal(errorMessage("boom"), "boom");
  assert.equal(errorMessage({}), "Request failed");
  assert.equal(errorMessage(null), "Request failed");
  assert.equal(errorMessage(undefined), "Request failed");
});

const srcRoot = fileURLToPath(new URL("..", import.meta.url));

const sweep = (message: string, pattern: RegExp): void => {
  const sourceFiles = readdirSync(srcRoot, { recursive: true, withFileTypes: true })
    // Test files carry the pattern as a literal, including this one.
    .filter((entry) => entry.isFile() && /\.tsx?$/.test(entry.name) && !/\.(test|spec)\.tsx?$/.test(entry.name))
    .map((entry) => join(entry.parentPath, entry.name));
  const hits: string[] = [];
  for (const file of sourceFiles) {
    readFileSync(file, "utf8")
      .split("\n")
      .forEach((line, index) => {
        if (pattern.test(line)) {
          hits.push(`${file.slice(srcRoot.length)}:${index + 1}`);
        }
      });
  }
  assert.deepEqual(hits, [], message);
};

test("no call site renders String((err as { message?: string })?.message ?? err)", () => {
  // Both the optional-chain `?.message` and the plain `.message` casts
  // existed in the codebase; the operand (x) is pinned by the backreference.
  sweep(
    "String(x?.message ?? x) renders [object Object]",
    /String\(\((\w+) as \{ message\?: string \}\)\??\.message \?\? \1\)/,
  );
});

const orStringSweep = /\((\w+) as \{ message\?: string \}\)\??\.message \|\| String\(\1\)/;

test("no call site renders (err as { message?: string })?.message || String(err)", () => {
  sweep("x?.message || String(x) renders [object Object]", orStringSweep);
});

test("the || sweep regex matches the non-optional .message spelling", () => {
  assert.match("(err as { message?: string })?.message || String(err)", orStringSweep);
  assert.match("(err as { message?: string }).message || String(err)", orStringSweep);
});
