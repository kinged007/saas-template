import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { isReadFailure } from "./read-failure.ts";

// The keys refine generates for its own error notifications, one per hook
// (node_modules/@refinedev/core/dist/index.mjs). The read hooks are the ones
// the app reports in-body; the mutation hooks are the ones that keep the toast.
const READ_KEYS = [
  "jobs-useList-notification",
  "job-123-getOne-notification",
  "job-123-getMany-notification",
  "jobs-useInfiniteList-notification",
  "get-notification",
];

const WRITE_KEYS = [
  "job-123-jobs-notification", // useUpdate / useDelete
  "job-123,124-jobs-notification", // useDeleteMany
  "1,2-jobs-updateMany-error-notification", // useUpdateMany
  "create-jobs-notification", // useCreate
  "createMany-jobs-notification", // useCreateMany
  "post-notification", // useCustomMutation
  "patch-notification",
  "delete-notification",
];

test("a failed read is recognised by refine's generated key", () => {
  for (const key of READ_KEYS) {
    assert.equal(isReadFailure({ type: "error", key }), true, key);
  }
});

test("a failed mutation is not", () => {
  for (const key of WRITE_KEYS) {
    assert.equal(isReadFailure({ type: "error", key }), false, key);
  }
});

test("only errors are read failures", () => {
  assert.equal(isReadFailure({ type: "success", key: "get-notification" }), false);
  assert.equal(isReadFailure({ type: "progress", key: "get-notification" }), false);
  // An app-authored notification carries no refine key.
  assert.equal(isReadFailure({ type: "error" }), false);
});

/**
 * Contract against the installed refine: every notification it generates
 * itself is dropped or kept by this predicate, so a version bump that renames
 * a key template has to be re-checked here instead of silently re-enabling the
 * duplicate toast (or silencing a mutation).
 */
test("matches the notification keys the installed refine generates", () => {
  const source = readFileSync(
    "node_modules/@refinedev/core/dist/index.mjs",
    "utf8",
  );
  // Attribute each generated notification to the hook declared before it.
  const declarations = [
    ...source.matchAll(/^var (use\w+) = /gm),
  ].map((match) => ({ hook: match[1], at: match.index! }));

  const hooks = new Map<string, string[]>();
  for (const match of source.matchAll(/key: `([^`]+)`,\n\s*message: translate\(/g)) {
    const owner = declarations.filter((d) => d.at < match.index!).pop();
    if (owner) {
      hooks.set(owner.hook, [
        ...(hooks.get(owner.hook) ?? []),
        match[1],
      ]);
    }
  }

  const READ_HOOKS = [
    "useList",
    "useOne",
    "useMany",
    "useCustom",
    "useInfiniteList",
  ];
  const WRITE_METHODS = ["post", "patch", "put", "delete"];

  for (const hook of READ_HOOKS) {
    const keys = hooks.get(hook) ?? [];
    assert.ok(keys.length > 0, `${hook} generates no notification key`);
    for (const key of keys) {
      const rendered = key.replace("${method}", "get");
      assert.equal(
        isReadFailure({ type: "error", key: rendered }),
        true,
        `${hook} key ${rendered} is not treated as a read failure`,
      );
    }
  }

  for (const [hook, keys] of hooks) {
    if (READ_HOOKS.includes(hook)) continue;
    for (const key of keys) {
      const methods = key.includes("${method}") ? WRITE_METHODS : [""];
      for (const method of methods) {
        const rendered = key.replace("${method}", method);
        assert.equal(
          isReadFailure({ type: "error", key: rendered }),
          false,
          `${hook} key ${rendered} is wrongly treated as a read failure`,
        );
      }
    }
  }
});