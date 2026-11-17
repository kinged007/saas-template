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

// Five call sites fall back to a literal (`?? "Export failed"`, `|| "Failed to delete workspace"`) rather than
// to `String(err)`, so the sweeps below do not cover them: components/WorkspaceExportCard.tsx:68 and
// pages/settings/workspace/sections/GeneralSection.tsx:139,179,203,480.
//
// The walk is line-based: a cast split over two lines is out of scope, as is a cast whose additional
// property is a nested object type (`{ message?: string; response?: { detail: string } }`), because a
// regex cannot balance braces.
const sweep = (message: string, pattern: RegExp): void => {
  const sourceFiles = readdirSync(srcRoot, { recursive: true, withFileTypes: true })
    // Test files carry the pattern as a literal, including this one.
    .filter((entry) => entry.isFile() && /\.tsx?$/.test(entry.name) && !/\.(test|spec)\.tsx?$/.test(entry.name))
    .map((entry) => join(entry.parentPath, entry.name));
  assert.ok(sourceFiles.length > 0, "sweep scanned no source files");
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


// The cast body is shared so both sweeps widen together: `[^}]*` covers the member separators this repo
// uses (`;`, `,`, `|`), cannot cross a `}`, and cannot cross a line break.
const cast = String.raw`\((\w+) as \{ message\?: string\b[^}]*\s*\}\)\??\.message`;
const nullishSweep = new RegExp(String.raw`String\(` + cast + String.raw` \?\? \1\)`);
const orStringSweep = new RegExp(cast + String.raw` \|\| String\(\1\)`);

test("no call site renders String((err as { message?: string })?.message ?? err)", () => {
  // Both the optional-chain `?.message` and the plain `.message` casts
  // existed in the codebase; the operand (x) is pinned by the backreference.
  sweep("String(x?.message ?? x) renders [object Object]", nullishSweep);
});

test("no call site renders (err as { message?: string })?.message || String(err)", () => {
  sweep("x?.message || String(x) renders [object Object]", orStringSweep);
});

test("the || sweep regex matches the non-optional .message spelling", () => {
  assert.match("(err as { message?: string })?.message || String(err)", orStringSweep);
  assert.match("(err as { message?: string }).message || String(err)", orStringSweep);
});

test("the ?? sweep regex matches the non-optional .message spelling", () => {
  assert.match("String((err as { message?: string })?.message ?? err)", nullishSweep);
  assert.match("String((err as { message?: string }).message ?? err)", nullishSweep);
});

// Call-site casts may carry additional properties, e.g. `{ message?: string; code?: string }`.
test("both sweeps catch casts with additional properties", () => {
  assert.match("(err as { message?: string; code?: string }).message || String(err)", orStringSweep);
  assert.match("(err as { message?: string; code?: string })?.message || String(err)", orStringSweep);
  assert.match("String((err as { message?: string; code?: string }).message ?? err)", nullishSweep);
  assert.match("String((err as { message?: string; code?: string })?.message ?? err)", nullishSweep);
  // `;`, `,` and `|` all separate members of the cast type.
  assert.match("(err as { message?: string, code?: string }).message || String(err)", orStringSweep);
  assert.match("String((err as { message?: string | null })?.message ?? err)", nullishSweep);
  // `\b` keeps `string` from matching a longer identifier.
  assert.doesNotMatch("(err as { message?: stringify }).message || String(err)", orStringSweep);
  // The operand stays pinned by the backreference even with the widened cast type.
  assert.doesNotMatch(
    "(err as { message?: string; code?: string }).message || String(other)",
    orStringSweep,
  );
  assert.doesNotMatch(
    "String((err as { message?: string; code?: string }).message ?? other)",
    nullishSweep,
  );
});
