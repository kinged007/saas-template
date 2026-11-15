import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

// Source-scan: the component is .tsx, which node --test cannot load, so its
// wiring is asserted on the text instead (same style as CopyButton.test.ts).
const table = readFileSync(
  fileURLToPath(new URL("./AuditLogTable.tsx", import.meta.url)),
  "utf8",
);
const section = readFileSync(
  fileURLToPath(
    new URL("../pages/settings/workspace/sections/AuditLogSection.tsx", import.meta.url),
  ),
  "utf8",
);

test("Export CSV button renders from exportUrl and downloads a blob", () => {
  assert.match(table, /exportUrl\?: string/);
  assert.match(table, /Export CSV/);
  assert.match(table, /responseType:\s*"blob"/);
  assert.match(table, /content-disposition/);
});

test("the download carries the submitted search as q", () => {
  assert.match(table, /params\.set\("q", submitted\)/);
  assert.match(table, /format.*csv/);
});

test("a 429 surfaces Retry-After instead of a generic failure", () => {
  assert.match(table, /resp\?\.status === 429/);
  assert.match(table, /retry-after/);
  assert.match(table, /Too many exports/);
});

test("settings audit section wires the export endpoint with search", () => {
  assert.match(section, /resource="audit"/);
  assert.match(section, /exportUrl="audit\/export"/);
  assert.match(section, /searchEnabled/);
});
