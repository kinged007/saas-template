import assert from "node:assert/strict";
import { test } from "node:test";

import type { MemberStatus } from "@/types";
import {
  canReactivateMember,
  canReceiveOwnership,
  canSuspendMember,
} from "./member-actions.ts";

const mem = (status: MemberStatus) => ({ status });

test("canSuspendMember offers Suspend on every status the API still acts on", () => {
  assert.equal(canSuspendMember(mem("active")), true);
  assert.equal(canSuspendMember(mem("invited")), true);
  assert.equal(canSuspendMember(mem("suspended")), false);
});

test("canReactivateMember offers Reactivate on a suspended member only", () => {
  assert.equal(canReactivateMember(mem("suspended")), true);
  assert.equal(canReactivateMember(mem("active")), false);
  assert.equal(canReactivateMember(mem("invited")), false);
});

test("canReceiveOwnership accepts an active member only", () => {
  assert.equal(canReceiveOwnership(mem("active")), true);
  assert.equal(canReceiveOwnership(mem("invited")), false);
  assert.equal(canReceiveOwnership(mem("suspended")), false);
});

test("a status outside the union gets neither action", () => {
  // The cast is the only way to spell "a status this app has never seen"; it
  // exercises the runtime behaviour, not a type error to fix.
  const future = { status: "archived" as unknown as MemberStatus };
  assert.equal(canSuspendMember(future), false);
  assert.equal(canReactivateMember(future), false);
  assert.equal(canReceiveOwnership(future), false);
});