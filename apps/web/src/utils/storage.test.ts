import { strict as assert } from "node:assert";
import { test } from "node:test";

import { onboardingStore } from "./storage.ts";

test("clear() undoes only the caller's own dismissal for that workspace", () => {
  onboardingStore.dismiss("w1", "u1");
  assert.equal(onboardingStore.isDismissed("w1", "u1"), true);
  assert.equal(onboardingStore.isDismissed("w1", "u2"), false);
  assert.equal(onboardingStore.isDismissed("w2", "u1"), false);

  onboardingStore.clear("w1", "u1");
  assert.equal(onboardingStore.isDismissed("w1", "u1"), false);
  assert.equal(onboardingStore.isDismissed("w2", "u1"), false);
});
