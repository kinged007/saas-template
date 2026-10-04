import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  getActiveWorkspaceId,
  identityStore,
  onboardingStore,
  resetSessionState,
  setActiveWorkspaceId,
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
  identityStore.set({ id: "u1" });

  resetSessionState();

  assert.equal(getActiveWorkspaceId(), null);
  assert.equal(workspaceStore.get(), null);
  assert.equal(workspaceStore.get("u2"), null);
  assert.equal(identityStore.get(), null);
});
