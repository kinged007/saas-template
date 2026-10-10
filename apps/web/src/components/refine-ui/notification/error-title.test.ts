import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { errorTitle } from "./error-title.ts";

// The #512 widening from (\d+) to (\S+) plus the guard change from
// /^\d{3}$/ to /^[1-5]\d\d$/ changed the result for ten of these (all but
// 0, 99 and 4040, which were dropped before it too — #396 matrix).
//
// One test() per token instead of a loop over one assert: a single run then
// reports every dropped token that regresses, not just the first failure.
for (const token of [
  "undefined", "null", "NaN", "0", "099", "600", "999",
  "ERR_NETWORK", "404.0", "1e3", "-1", "99", "4040",
])
  test(`errorTitle drops status token ${JSON.stringify(token)}`, () => {
    assert.equal(errorTitle(`Error (status code: ${token})`), "Error");
  });

test("errorTitle keeps a real HTTP status", () => {
  assert.equal(
    errorTitle("Error (status code: 404)"),
    "Error (status code: 404)",
  );
  assert.equal(
    errorTitle("Error (status code: 500)"),
    "Error (status code: 500)",
  );
  assert.equal(
    errorTitle("Error (status code: 401)"),
    "Error (status code: 401)",
  );
});

test("errorTitle keeps a message without a status suffix", () => {
  assert.equal(errorTitle("Network Error"), "Network Error");
  assert.equal(errorTitle("TypeError"), "TypeError");
  assert.equal(errorTitle("Error"), "Error");
  assert.equal(
    errorTitle("status code: 404 is not a suffix"),
    "status code: 404 is not a suffix",
  );
  // #397: @refinedev/core@5.0.12 ships a useCreateMany/useUpdateMany title
  // template missing its closing paren, so there is no complete suffix to
  // drop — pass the upstream title through untouched.
  assert.equal(
    errorTitle("There was an error creating user (status code: 0"),
    "There was an error creating user (status code: 0",
  );
});

test("errorTitle matches the suffix at the end, parentheses and all", () => {
  assert.equal(
    errorTitle("Validation failed (field: email) (status code: 422)"),
    "Validation failed (field: email) (status code: 422)",
  );
  assert.equal(
    errorTitle("Validation failed (field: email) (status code: undefined)"),
    "Validation failed (field: email)",
  );
  assert.equal(
    errorTitle("Retry (status code: 404) failed (status code: undefined)"),
    "Retry (status code: 404) failed",
  );
});

// Source-scan: the provider is .tsx, which node --test cannot load, so its
// wiring is asserted on the text instead. fileURLToPath around the URL is
// the convention the sibling source scans follow (CopyButton.test.ts,
// SecuritySection.test.ts) — readFileSync accepts either form, so keep
// this one wrapped and the reads uniform.
const provider = readFileSync(
  fileURLToPath(new URL("./use-notification-provider.tsx", import.meta.url)),
  "utf8",
);

test('useNotificationProvider routes type: "error" toasts through errorTitle', () => {
  assert.match(
    provider,
    /import \{ errorTitle \} from "@\/components\/refine-ui\/notification\/error-title"/,
  );
  const start = provider.indexOf('case "error":');
  const end = provider.indexOf('case "progress":');
  assert.notEqual(start, -1, 'case "error" missing from the provider');
  assert.ok(end > start, 'case "progress" missing after the error case');
  assert.ok(
    provider.slice(start, end).includes("toast.error(errorTitle(message)"),
    'the "error" case must render toast.error(errorTitle(message))',
  );
});
