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

// Row-level spec: a pending revoke must disable only its own row. The button
// therefore lives in the SessionRevokeButton child, which owns the mutation
// for exactly one session id (hooks cannot live in the .map loop), the same
// pattern the member editor ships since #1354.
const child = source.slice(
  source.indexOf("function SessionRevokeButton"),
  source.indexOf("export function SecuritySection"),
);
const parent = source.slice(source.indexOf("export function SecuritySection"));

test("the row Revoke action lives in a child owning its own mutation", () => {
  assert.ok(child.startsWith("function SessionRevokeButton"), "SessionRevokeButton child missing");
  assert.ok(child.includes("useCustomMutation()"), "child does not own a mutation");
  assert.ok(child.includes("mutation.isPending"), "child does not bind its own isPending");
  assert.ok(child.includes('method: "delete"'), "child does not send the revoke request");
  assert.ok(child.includes("errorNotification: false"), "child does not suppress generic toasts");
  assert.ok(child.includes("onRevoked()"), "child does not notify after revoking");
});

test("each row renders that child keyed by its session id", () => {
  assert.ok(
    parent.includes("<SessionRevokeButton") && parent.includes("sessionId={s.id}"),
    "rows do not render SessionRevokeButton with the row's session id",
  );
});

test("the shared revoke-one mutation and handler are gone", () => {
  assert.ok(!source.includes("revokeOne"), "revoke-one leftovers present in the section");
});

test("no section action shares one useCustomMutation across change-password and 2FA", () => {
  const shared = parent
    .split("\n")
    .filter((line) => /const \{\s*mutateAsync,\s*mutation\s*\}\s*=\s*useCustomMutation\(\)/.test(line));
  assert.equal(shared.length, 0, `shared mutation still present: ${shared.join("; ")}`);
});

test("each remaining section action owns its mutation and binds its own isPending", () => {
  for (const name of [
    "changePasswordMutation",
    "setupMutation",
    "enableMutation",
    "disableMutation",
    "revokeAllMutation",
  ]) {
    assert.ok(parent.includes(`mutation: ${name}`), `missing per-action mutation: ${name}`);
  }
  const pending = parent.split("\n").filter((line) => line.includes(".isPending"));
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
