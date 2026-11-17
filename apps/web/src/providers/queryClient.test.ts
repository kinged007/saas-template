import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import {
  isClientError,
  isNoResponseError,
  isServerError,
  queryClient,
  shouldRetry,
} from "./queryClient.ts";

const srcDir = join(dirname(fileURLToPath(import.meta.url)), "..");

const retry = queryClient.getDefaultOptions().queries?.retry as (
  failureCount: number,
  error: unknown,
) => boolean;

// Matches a real override (`retry: false`, `retry: true`, `retry: 2`,
// `retry: (…) =>`), not a prop type or a JSX attribute that happens to be
// called retry. `retry: true` retries forever, so it must not slip past.
// ponytail: a retry bound to an identifier (`retry: RETRY_BUDGET`) is not
// detected; extend the alternation when one appears, do not loosen the
// pattern into matching JSX props.
const RETRY_OVERRIDE = /retry:\s*(true|false|\d|\()/;

test("a 4xx is never retried", () => {
  for (const statusCode of [400, 401, 403, 404, 409, 422, 429, 499]) {
    assert.equal(retry(0, { statusCode }), false, `status ${statusCode}`);
    assert.equal(isClientError({ statusCode }), true, `isClientError ${statusCode}`);
  }
});

test("a request with no response is never retried", () => {
  assert.equal(retry(0, { statusCode: 0 }), false);
  assert.equal(isNoResponseError({ statusCode: 0 }), true);
  assert.equal(isNoResponseError({ statusCode: 500 }), false);
  assert.equal(isNoResponseError({}), false);
});

test("an unknown error stays retryable", () => {
  for (const error of [{}, null, undefined]) {
    assert.equal(retry(0, error), true, JSON.stringify(error));
    assert.equal(isClientError(error), false, JSON.stringify(error));
  }
});

test("a 5xx is never retried", () => {
  for (const statusCode of [500, 502, 503, 504, 599]) {
    assert.equal(retry(0, { statusCode }), false, `status ${statusCode}`);
    assert.equal(isServerError({ statusCode }), true, `isServerError ${statusCode}`);
  }
  assert.equal(isServerError({}), false);
});

// react-query's default retryDelay ramps 1s -> 2s -> 4s; retrying a 4xx is
// what put ~7s of "Loading…" in front of every refusal.
test("the refusal is what costs a retry", () => {
  assert.equal(retry(2, { statusCode: 404 }), false);
});

test("shouldRetry is the one refusal policy at any budget", () => {
  // No response, 4xx, 5xx: refused on the first attempt, whatever the budget.
  for (const max of [2, 3]) {
    for (const error of [{ statusCode: 0 }, { statusCode: 404 }, { statusCode: 500 }]) {
      assert.equal(shouldRetry(0, error, max), false, `max ${max} ${JSON.stringify(error)}`);
    }
    // An unknown error rides the budget: `max` retries, then it stops.
    assert.equal(shouldRetry(max - 1, {}, max), true, `max ${max}`);
    assert.equal(shouldRetry(max, {}, max), false, `max ${max}`);
  }
});

// The identity override cannot be imported here (its .tsx drags in React),
// so its drift pin is a source scan, same style as the retry-override audit.
test("both retry call sites route through the shared refusal policy", () => {
  const identity = readFileSync(join(srcDir, "contexts/WorkspaceContext.tsx"), "utf8");
  assert.match(identity, /shouldRetry\(failureCount, error, 2\)/);
  assert.doesNotMatch(identity, /isClientError|isNoResponseError|isServerError/);

  const client = readFileSync(join(srcDir, "providers/queryClient.ts"), "utf8");
  assert.match(client, /retry: \(failureCount, error\) => shouldRetry\(failureCount, error, 3\)/);
});

test("the retry-override scan catches an unbounded retry", () => {
  for (const override of [
    "queryOptions: { retry: true }",
    "queryOptions: { retry: false }",
    "queryOptions: { retry: 2 }",
    "retry: (failureCount) => failureCount < 2",
  ]) {
    assert.equal(RETRY_OVERRIDE.test(override), true, override);
  }
  for (const notAnOverride of ["<Button retry={false} />", "retry: RetryPolicy"]) {
    assert.equal(RETRY_OVERRIDE.test(notAnOverride), false, notAnOverride);
  }
});

test("an explicit retry budget is set only where it is audited", () => {
  const sources = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) return sources(path);
      return /\.tsx?$/.test(entry.name) && !/\.test\.ts$/.test(entry.name) ? [path] : [];
    });
  const hits = sources(srcDir)
    .filter((path) => RETRY_OVERRIDE.test(readFileSync(path, "utf8")))
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
