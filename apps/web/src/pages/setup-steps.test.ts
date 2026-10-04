import assert from "node:assert/strict";
import { test } from "node:test";

import { setupSteps } from "./setup-steps.ts";

const noneYet = { invitationCount: 0, apiKeyCount: 0 };

test("a step the identity may not perform is omitted, so the card can complete", () => {
  const steps = setupSteps({ ...noneYet, canInvite: false, canTrackKeyStep: false });

  // `every` over an empty list is what makes `allDone` true in the page. Read
  // before the deepEqual below, whose assertion signature would narrow it.
  assert.equal(
    steps.every((s) => s.done),
    true,
  );
  assert.deepEqual(steps, []);
});

test("a permitted step is kept and takes its progress from its own data", () => {
  const open = setupSteps({ ...noneYet, canInvite: true, canTrackKeyStep: true });
  assert.deepEqual(
    open.map((s) => [s.title, s.done]),
    [
      ["Invite your team", false],
      ["Create an API key", false],
    ],
  );

  const invited = setupSteps({
    invitationCount: 2,
    apiKeyCount: 0,
    canInvite: true,
    canTrackKeyStep: true,
  });
  assert.deepEqual(
    invited.map((s) => s.done),
    [true, false],
  );
  // The link is what the step's call to action navigates to.
  assert.deepEqual(
    open.map((s) => s.to),
    ["/members", "/api-keys/create"],
  );
});

test("only the step the identity may not perform is omitted", () => {
  const steps = setupSteps({ ...noneYet, canInvite: false, canTrackKeyStep: true });

  assert.deepEqual(
    steps.map((s) => s.title),
    ["Create an API key"],
  );
  assert.equal(
    steps.every((s) => s.done),
    false,
  );
});

test("a permission that has not resolved yet counts as missing", () => {
  // `useCan` returns undefined while it loads. Rendering the call to action
  // first and dropping it a tick later reads worse than the brief omission.
  assert.deepEqual(setupSteps(noneYet), []);
});