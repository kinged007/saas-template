import assert from "node:assert/strict";
import { test } from "node:test";

import { hasRefreshLock, withRefreshLock } from "./refreshLock.ts";

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

test("serialises concurrent callers so only one exchanges the token", async () => {
  const gate = deferred<void>();
  const order: string[] = [];
  const run = (tag: string) =>
    withRefreshLock(async () => {
      order.push(`enter:${tag}`);
      await gate.promise;
      order.push(`exit:${tag}`);
    });

  const a = run("a");
  const b = run("b");
  // a holds the lock; b must not have entered yet.
  assert.deepEqual(order, ["enter:a"]);
  gate.resolve();
  await Promise.all([a, b]);
  // b ran only after a released — the whole point of the lock.
  assert.deepEqual(order, ["enter:a", "exit:a", "enter:b", "exit:b"]);
});

test("a rejected holder still releases the lock", async () => {
  const failing = withRefreshLock(async () => {
    throw new Error("refresh failed");
  });
  await assert.rejects(failing, /refresh failed/);
  assert.equal(await withRefreshLock(async () => "recovered"), "recovered");
});

test("falls back to a direct call when the Web Locks API is absent", async () => {
  const real = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", { value: {}, configurable: true });
  try {
    assert.equal(hasRefreshLock(), false);
    // no lock, so both callers are inside at once
    const gate = deferred<void>();
    const order: string[] = [];
    const run = (tag: string) =>
      withRefreshLock(async () => {
        order.push(`enter:${tag}`);
        await gate.promise;
        order.push(`exit:${tag}`);
      });
    const a = run("a");
    const b = run("b");
    assert.deepEqual(order, ["enter:a", "enter:b"]);
    gate.resolve();
    await Promise.all([a, b]);
  } finally {
    if (real) Object.defineProperty(globalThis, "navigator", real);
  }
});
