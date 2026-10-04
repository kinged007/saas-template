import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { isClientError, queryClient } from "./queryClient.ts";

const srcDir = join(dirname(fileURLToPath(import.meta.url)), "..");

const retry = queryClient.getDefaultOptions().queries?.retry as (
  failureCount: number,
  error: unknown,
) => boolean;

test("a 4xx is never retried", () => {
  for (const statusCode of [400, 401, 403, 404, 409, 422, 429, 499]) {
    assert.equal(retry(0, { statusCode }), false, `status ${statusCode}`);
    assert.equal(isClientError({ statusCode }), true, `isClientError ${statusCode}`);
  }
});

test("a 5xx, an absent response and an unknown error stay retryable", () => {
  // statusCode 0 is dataProvider's "no HTTP response" sentinel (offline,
  // DNS, CORS, abort) — the response may exist on the next attempt.
  for (const error of [{ statusCode: 500 }, { statusCode: 503 }, { statusCode: 0 }, {}, null, undefined]) {
    assert.equal(retry(0, error), true, JSON.stringify(error));
    assert.equal(isClientError(error), false, JSON.stringify(error));
  }
});

test("the retry budget is 3 retries for 5xx, and the refusal is what costs a retry", () => {
  assert.equal(retry(2, { statusCode: 500 }), true);
  assert.equal(retry(3, { statusCode: 500 }), false);
  // react-query's default retryDelay ramps 1s -> 2s -> 4s; retrying a 4xx is
  // what put ~7s of "Loading…" in front of every refusal.
  assert.equal(retry(2, { statusCode: 404 }), false);
});

test("an explicit retry budget is set only where it is audited", () => {
  const sources = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) return sources(path);
      return /\.tsx?$/.test(entry.name) && !/\.test\.ts$/.test(entry.name) ? [path] : [];
    });
  // Matches a real override (`retry: false`, `retry: 2`, `retry: (…) =>`), not
  // a prop type or a JSX attribute that happens to be called retry.
  const hits = sources(srcDir)
    .filter((path) => /retry:\s*(false|\d|\()/.test(readFileSync(path, "utf8")))
    .map((path) => relative(srcDir, path))
    .sort();
  assert.deepEqual(hits, [
    "components/WorkspaceExportCard.tsx", // no-storm path: e2e asserts one attempt on network failure
    "components/WorkspaceSearch.tsx", // key contains the query text, so a retry is always superseded
    "contexts/WorkspaceContext.tsx", // refine hardcodes retry:false for useGetIdentity
    "pages/InboxPage.tsx", // one attempt on a network failure; the pane renders its own error line
    "providers/queryClient.ts", // the default itself
  ]);
});
