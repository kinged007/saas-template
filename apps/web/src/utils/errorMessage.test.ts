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

test("no call site renders String((err as { message?: string })?.message ?? err)", () => {
  const sourceFiles = readdirSync(srcRoot, { recursive: true, withFileTypes: true })
    // Test files carry the pattern as a literal, including this one.
    .filter((entry) => entry.isFile() && /\.tsx?$/.test(entry.name) && !entry.name.endsWith(".test.ts"))
    .map((entry) => join(entry.parentPath, entry.name));
  const hits: string[] = [];
  for (const file of sourceFiles) {
    readFileSync(file, "utf8")
      .split("\n")
      .forEach((line, index) => {
        if (/String\(\((\w+) as \{ message\?: string \}\)\?\.message \?\? \1\)/.test(line)) {
          hits.push(`${file.slice(srcRoot.length)}:${index + 1}`);
        }
      });
  }
  // Without errorMessage these render "[object Object]"; the message-carrying
  // form is the fix, so none of the call sites may go back to it.
  assert.equal(hits.length, 0, `String(x?.message ?? x) renders [object Object]: ${hits.join(", ")}`);
});
