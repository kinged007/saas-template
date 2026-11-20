import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source = readFileSync(new URL("./AppLayout.tsx", import.meta.url), "utf8");

// `assert.match` echoes the whole haystack on failure, which is the whole
// component. These asserts take a message so a red run prints one line.
test("AppLayout calls useSingleWorkspace once", () => {
  // `(?!:)` skips the declaration `function useSingleWorkspace(): boolean`.
  const callSites = source.match(/useSingleWorkspace\(\)(?!:)/g) ?? [];
  assert.equal(callSites.length, 1, `expected 1 useSingleWorkspace() call, found ${callSites.length}`);
});

test("the switcher receives the boolean, not the query", () => {
  const signature = "function WorkspaceSwitcher({ single }: { single: boolean })";
  assert.ok(source.includes(signature), `WorkspaceSwitcher must take ${signature}`);
});
