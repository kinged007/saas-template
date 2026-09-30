import assert from "node:assert/strict";
import { test } from "node:test";

import { canResendInvitation, canRevokeInvitation, invitationStatus } from "./invitation-actions.ts";

const inv = (status: string, expired = false) => ({ status, expired });

// Delete (revoke) and Re-send must not both offer a one-click reversal of each
// other, and both must match what the API allows for a given status.
test("canRevokeInvitation offers Delete on a live invitation only", () => {
  assert.equal(canRevokeInvitation(inv("pending", false)), true);
  assert.equal(canRevokeInvitation(inv("pending", true)), true);
  assert.equal(canRevokeInvitation(inv("declined")), false);
  assert.equal(canRevokeInvitation(inv("revoked")), false);
  assert.equal(canRevokeInvitation(inv("accepted")), false);
});

test("canResendInvitation is off on the terminal statuses", () => {
  assert.equal(canResendInvitation(inv("revoked")), false);
  assert.equal(canResendInvitation(inv("revoked", true)), false);
  assert.equal(canResendInvitation(inv("accepted")), false);
});

test("canResendInvitation offers Re-send on a declined row", () => {
  assert.equal(canResendInvitation(inv("declined")), true);
});

test("canResendInvitation needs an expired pending row", () => {
  // A fresh pending row is a no-op server-side: the service returns it unchanged.
  assert.equal(canResendInvitation(inv("pending", false)), false);
  assert.equal(canResendInvitation(inv("pending", true)), true);
});

test("invitationStatus reports an expired pending row as expired", () => {
  // A plain pending badge next to a past expiry date reads as still live.
  assert.equal(invitationStatus(inv("pending", true)), "expired");
  assert.equal(invitationStatus(inv("pending", false)), "pending");
});

test("invitationStatus leaves the other statuses alone", () => {
  assert.equal(invitationStatus(inv("accepted")), "accepted");
  assert.equal(invitationStatus(inv("revoked", true)), "revoked");
  assert.equal(invitationStatus(inv("declined")), "declined");
});
