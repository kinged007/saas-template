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
const shared = readFileSync(
  fileURLToPath(new URL("../../components/SessionRevokeButton.tsx", import.meta.url)),
  "utf8",
);
const memberSource = readFileSync(
  fileURLToPath(new URL("../../user/sections/SecuritySection.tsx", import.meta.url)),
  "utf8",
);

// Row-level spec: a pending revoke must disable only its own row. The button
// therefore lives in the shared SessionRevokeButton child, which owns the
// mutation for exactly one session id (hooks cannot live in the .map loop).
const child = shared;
const parent = source.slice(source.indexOf("export function SecuritySection"));

test("the row Revoke action lives in a child owning its own mutation", () => {
  assert.ok(child.includes("function SessionRevokeButton"), "SessionRevokeButton child missing");
  assert.ok(child.includes("useCustomMutation()"), "child does not own a mutation");
  assert.ok(child.includes("mutation.isPending"), "child does not bind its own isPending");
  assert.ok(child.includes('method: "delete"'), "child does not send the revoke request");
  assert.ok(child.includes("errorNotification: false"), "child does not suppress generic toasts");
  assert.ok(child.includes("onRevoked()"), "child does not notify after revoking");
});

test("both sections share that child instead of a file-local copy", () => {
  for (const [name, text] of [
    ["profile", source],
    ["member", memberSource],
  ] as const) {
    assert.ok(!text.includes("function SessionRevokeButton"), `${name} still carries a file-local copy`);
    assert.ok(
      text.includes('from "../../components/SessionRevokeButton"'),
      `${name} does not import the shared SessionRevokeButton`,
    );
    assert.ok(
      text.includes("<SessionRevokeButton") && text.includes("sessionId={s.id}"),
      `${name} rows do not render SessionRevokeButton with the row's session id`,
    );
  }
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

test("the setup-key copy button goes through the shared CopyButton", () => {
  assert.ok(
    source.includes('<CopyButton'),
    "inline copy button still hand-rolled in SecuritySection",
  );
  assert.ok(
    source.includes('label="Copy setup key"'),
    "CopyButton not given the setup-key label",
  );
  assert.ok(
    !source.includes("const copyLabel"),
    "local copyLabel still deriving the name CopyButton already derives",
  );
});

// A session revoke cannot change 2FA state, so the revoke paths must refetch

test("the row revoke refetch uses the sessions-only refetch", () => {
  assert.ok(
    /onRevoked=\{\(\)\s*=>\s*sessions\.query\.refetch\(\)\}/.test(parent),
    "row revoke still wired to the dual refetch",
  );
});

test("revoke-all refetches sessions only", () => {
  const start = parent.indexOf("const revokeAll = async");
  const end = parent.indexOf("const startSetup = async");
  assert.ok(start >= 0 && end > start, "revokeAll body not found");
  const body = parent.slice(start, end);
  assert.ok(body.includes("sessions.query.refetch()"), "revokeAll does not refetch sessions");
  assert.ok(body.includes("refresh()") === false, "revokeAll still triggers the dual refetch");
});

test("the dual refresh stays reserved for the 2FA actions", () => {
  const enableCtx = parent.slice(parent.indexOf("const confirmSetup = async"), parent.indexOf("const disable = async"));
  const disableCtx = parent.slice(parent.indexOf("const disable = async"), parent.indexOf("const changePassword = async"));
  assert.ok(enableCtx.includes("refresh()"), "2FA enable no longer refreshes both queries");
  assert.ok(disableCtx.includes("refresh()"), "2FA disable no longer refreshes both queries");
  assert.equal(
    parent.split("refresh()").length - 1,
    2,
    "refresh must have exactly the two 2FA call sites",
  );
});
