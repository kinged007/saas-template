import assert from "node:assert/strict";
import { test } from "node:test";

import {
  getActiveWorkspaceId,
  identityStore,
  setActiveWorkspaceId,
  workspaceStore,
} from "./storage.ts";
import { postCredentials } from "./credentialPost.ts";

// The outgoing session, as a previous sign-in left it: an active workspace id
// in memory and the selection + identity in localStorage. The axios request
// interceptor reads the first synchronously and falls back to the other two, so
// any of them reaching a credential POST puts the outgoing workspace on the
// wire.
const outgoingSession = () => {
  setActiveWorkspaceId("ws-outgoing");
  workspaceStore.set("ws-outgoing", "user-outgoing");
  identityStore.set({ id: "user-outgoing" });
};

test("the outgoing workspace and identity are gone before the credential POST", async () => {
  outgoingSession();
  let activeAtSend: string | null | undefined;
  let identityAtSend: unknown;

  const tokens = await postCredentials(async () => {
    activeAtSend = getActiveWorkspaceId();
    identityAtSend = identityStore.get();
    return { access_token: "new" };
  });

  assert.equal(activeAtSend, null);
  assert.equal(identityAtSend, null);
  // The interceptor's last-resort fallback reads the legacy keys, which
  // resetSessionState() drops. The per-user entry stays — seedWorkspace reads
  // the incoming user's own selection back — and is unreachable once the
  // cached identity is gone.
  assert.equal(workspaceStore.get(), null);
  assert.deepEqual(tokens, { access_token: "new" });
});

test("a rejected credential POST leaves no outgoing identity to send", async () => {
  outgoingSession();

  await assert.rejects(
    postCredentials(async () => {
      throw new Error("invalid credentials");
    }),
    /invalid credentials/,
  );

  assert.equal(getActiveWorkspaceId(), null);
  assert.equal(identityStore.get(), null);
  assert.equal(workspaceStore.get(), null);
});
