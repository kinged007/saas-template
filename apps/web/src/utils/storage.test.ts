import { strict as assert } from "node:assert";
import { test } from "node:test";

import { onboardingStore, returnToStore } from "./storage.ts";

test("clear() undoes only the caller's own dismissal for that workspace", () => {
  onboardingStore.dismiss("w1", "u1");
  assert.equal(onboardingStore.isDismissed("w1", "u1"), true);
  assert.equal(onboardingStore.isDismissed("w1", "u2"), false);
  assert.equal(onboardingStore.isDismissed("w2", "u1"), false);

  onboardingStore.clear("w1", "u1");
  assert.equal(onboardingStore.isDismissed("w1", "u1"), false);
  assert.equal(onboardingStore.isDismissed("w2", "u1"), false);
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
