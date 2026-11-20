import assert from "node:assert/strict";
import { test } from "node:test";

import type { InvitationStatus } from "@/types";
import {
  canResendInvitation,
  canRevokeInvitation,
  invitationStatus,
  isActionableInvitation,
} from "./invitation-actions.ts";

const inv = (status: InvitationStatus, expired = false) => ({ status, expired });

// Delete (revoke) and Re-send must both match what the API allows for a given
// status; a `pending` row past its expiry is the one status that offers both.
test("canRevokeInvitation offers Delete on a live invitation only", () => {
  assert.equal(canRevokeInvitation(inv("pending", false)), true);
  assert.equal(canRevokeInvitation(inv("pending", true)), true);
  assert.equal(canRevokeInvitation(inv("declined")), false);
  assert.equal(canRevokeInvitation(inv("revoked")), false);
  assert.equal(canRevokeInvitation(inv("accepted")), false);
});

test("isActionableInvitation offers Accept/Decline on a live pending row only", () => {
  assert.equal(isActionableInvitation(inv("pending", false)), true);
  assert.equal(isActionableInvitation(inv("pending", true)), false);
  assert.equal(isActionableInvitation(inv("declined")), false);
  assert.equal(isActionableInvitation(inv("accepted")), false);
  assert.equal(isActionableInvitation(inv("revoked")), false);
});

test("isActionableInvitation treats an absent expired flag as live", () => {
  // `expired` is optional on the invitation shape and may be absent.
  assert.equal(isActionableInvitation({ status: "pending" }), true);
});

test("canResendInvitation is off on the terminal statuses", () => {
  assert.equal(canResendInvitation(inv("revoked")), false);
  assert.equal(canResendInvitation(inv("revoked", true)), false);
  assert.equal(canResendInvitation(inv("accepted")), false);
});

test("canResendInvitation offers Re-send on a declined row", () => {
  assert.equal(canResendInvitation(inv("declined")), true);
});

test("canResendInvitation offers Re-send on an expired row", () => {
  assert.equal(canResendInvitation(inv("expired")), true);
});

test("canResendInvitation denies a status outside the union", () => {
  // The cast is the only way to spell "a status this app has never seen"; it
  // exercises the runtime behaviour, not a type error to fix.
  const future = { status: "suspended" as unknown as InvitationStatus, expired: false };
  assert.equal(canResendInvitation(future), false);
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
