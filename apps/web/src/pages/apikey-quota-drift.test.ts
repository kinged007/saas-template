import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "..",
);

// The create form's usage_quota ceiling must equal the backend MAX_QUOTA
// Integer column ceiling. Each lives in a stack the other cannot import, so
// this test parses both and fails when they drift.
const backend = readFileSync(
  join(repoRoot, "apps/api/src/models/api_key.py"),
  "utf8",
);
const web = readFileSync(
  join(repoRoot, "apps/web/src/pages/ApiKeyCreatePage.tsx"),
  "utf8",
);

function backendMaxQuota(source: string): number {
  const expression = source.match(/^MAX_QUOTA\s*=\s*(.+)$/m)?.[1];
  assert.ok(expression, "MAX_QUOTA definition not found in models/api_key.py");
  // Only allow an arithmetic expression of integer literals; the backend
  // stays the source of truth, anything odd must fail loudly here.
  assert.match(
    expression,
    /^[\d\s*/+\-()]+$/,
    `unexpected MAX_QUOTA expression: ${expression}`,
  );
  return Function(`"use strict"; return (${expression});`)();
}

function webQuotaMax(source: string): number {
  const max = source.match(
    /usage_quota:\s*z\.number\(\)\.int\(\)\.min\(1\)\.max\((\d+)\)/,
  )?.[1];
  assert.ok(max, "usage_quota zod .max() bound not found in ApiKeyCreatePage");
  return Number(max);
}

test("ApiKeyCreatePage usage_quota max equals the backend MAX_QUOTA", () => {
  const backendMax = backendMaxQuota(backend);
  const webMax = webQuotaMax(web);
  assert.equal(
    webMax,
    backendMax,
    `web bound ${webMax} drifted from backend MAX_QUOTA ${backendMax}`,
  );
});
