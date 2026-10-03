import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { jobFetchError } from "./job-fetch-error.ts";

const page = (name: string): string =>
  readFileSync(new URL(name, import.meta.url), "utf8");

const jobDetail = page("JobDetailPage.tsx");
const jobRun = page("JobRunPage.tsx");

/** The props object of the `useWorkspaceCustom` call whose url literal is `url`. */
const fetchOptions = (source: string, url: string): string => {
  const at = source.indexOf(`url: \`${url}\``);
  assert.notEqual(at, -1, `no useWorkspaceCustom call fetches ${url}`);
  return source.slice(source.lastIndexOf("({", at), source.indexOf("});", at));
};

test("the refusal detail is what the body renders, not a status code", () => {
  assert.equal(
    jobFetchError({
      statusCode: 403,
      message: "you are not a member of this workspace",
    }),
    "you are not a member of this workspace",
  );
  assert.equal(jobFetchError({ statusCode: 404, message: "job not found" }), "job not found");
});

test("a query that did not fail leaves the page's own copy", () => {
  assert.equal(jobFetchError(undefined), undefined);
  assert.equal(jobFetchError(null), undefined);
  assert.equal(jobFetchError({}), undefined);
});

// The job pages render a failed fetch in-body, so refine must not also toast it
// (AGENTS.md: suppress the generic notification when the page shows the detail).
// `node --test` cannot render a .tsx, so read the calls instead.
test("a fetch the page renders its failure for does not toast it as well", () => {
  assert.match(fetchOptions(jobDetail, "jobs/${jobId}"), /errorNotification: false/);
  assert.match(fetchOptions(jobRun, "jobs/runs/${runId}"), /errorNotification: false/);
  // The heading's job fetch only supplies a name — its failure costs nothing else.
  assert.match(fetchOptions(jobRun, "jobs/${jobId}"), /errorNotification: false/);
});

test("each page shows the detail above its not-found copy", () => {
  assert.match(jobDetail, /jobFetchError\(jobQuery\.error\)/);
  assert.match(jobDetail, /Job not found\./);
  assert.match(jobRun, /jobFetchError\(runQuery\.error\)/);
  assert.match(jobRun, /Run not found\./);
});