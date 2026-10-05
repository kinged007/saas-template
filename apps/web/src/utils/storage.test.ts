import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  getActiveWorkspaceId,
  identityStore,
  onboardingStore,
  resetSessionState,
  returnToStore,
  setActiveWorkspaceId,
  tokenStore,
  workspaceStore,
} from "./storage.ts";

test("clear() undoes only the caller's own dismissal for that workspace", () => {
  onboardingStore.dismiss("w1", "u1");
  assert.equal(onboardingStore.isDismissed("w1", "u1"), true);
  assert.equal(onboardingStore.isDismissed("w1", "u2"), false);
  assert.equal(onboardingStore.isDismissed("w2", "u1"), false);

  onboardingStore.clear("w1", "u1");
  assert.equal(onboardingStore.isDismissed("w1", "u1"), false);
  assert.equal(onboardingStore.isDismissed("w2", "u1"), false);
});

test("resetSessionState() drops the outgoing user's active workspace and identity", () => {
  setActiveWorkspaceId("w1");
  workspaceStore.set("w1");
  workspaceStore.set("w2", "u2");
  identityStore.set({ id: "u1" });

  resetSessionState();

  assert.equal(getActiveWorkspaceId(), null);
  assert.equal(workspaceStore.get(), null);
  assert.equal(identityStore.get(), null);
  // The incoming user's own selection survives — seedWorkspace reads it back.
  assert.equal(workspaceStore.get("u2"), "w2");
});

test("returnToStore.take() returns the stored path and clears it", () => {
  returnToStore.set("/api-keys?page=2");

  assert.equal(returnToStore.take(), "/api-keys?page=2");
  assert.equal(returnToStore.take(), null);
});

test("returnToStore.take() is null when nothing was stored", () => {
  returnToStore.take();

  assert.equal(returnToStore.take(), null);
});

test("a throwing token listener is traced and cannot break the others", () => {
  const boom = new Error("socket failed");
  const throwing = () => {
    throw boom;
  };
  const logged: unknown[][] = [];
  const realError = console.error;
  console.error = (...args: unknown[]) => {
    logged.push(args);
  };
  const notified: string[] = [];
  const offThrowing = tokenStore.onTokensChanged(throwing);
  const offNext = tokenStore.onTokensChanged(() => notified.push("next"));

  try {
    tokenStore.setTokens("token");
  } finally {
    offThrowing();
    offNext();
    console.error = realError;
  }

  assert.deepEqual(notified, ["next"], "later listeners still run");
  assert.equal(logged.length, 1, "the swallowed error leaves a trace");
  assert.match(String(logged[0][0]), /tokenStore/);
  assert.equal(logged[0][1], throwing, "the subscriber is logged");
  assert.equal(logged[0][2], boom, "the error is logged");
});
