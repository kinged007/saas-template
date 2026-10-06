import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

// Source-scan: the section is .tsx, which node --test cannot load, so the
// wiring is asserted on the text instead (same style as errorMessage.test.ts).
const source = readFileSync(
  fileURLToPath(new URL("./SecuritySection.tsx", import.meta.url)),
  "utf8",
);

test("no action shares one useCustomMutation across change-password, 2FA, and revokes", () => {
  const shared = source
    .split("\n")
    .filter((line) => /const \{\s*mutateAsync,\s*mutation\s*\}\s*=\s*useCustomMutation\(\)/.test(line));
  assert.equal(shared.length, 0, `shared mutation still present: ${shared.join("; ")}`);
});

test("each action owns its mutation and binds its own isPending", () => {
  for (const name of [
    "changePasswordMutation",
    "setupMutation",
    "enableMutation",
    "disableMutation",
    "revokeOneMutation",
    "revokeAllMutation",
  ]) {
    assert.ok(source.includes(`mutation: ${name}`), `missing per-action mutation: ${name}`);
  }
  const pending = source.split("\n").filter((line) => line.includes(".isPending"));
  assert.ok(pending.length > 0, "expected per-action isPending bindings");
  const bare = pending.filter((line) => !/[A-Za-z]Mutation\.isPending/.test(line));
  // An in-flight 2FA setup must not disable Change password and vice versa.
  assert.equal(bare.length, 0, `shared pending binding still present: ${bare.join("; ")}`);
});

test("the 2FA setup-key clipboard catch renders through the shared errorMessage helper", () => {
  assert.ok(source.includes('from "@/utils/errorMessage"'), "missing errorMessage import");
  assert.ok(source.includes("description: errorMessage("), "clipboard catch skips errorMessage");
  assert.ok(!source.includes('"Copy failed"'), "stale clipboard fallback still present");
});
