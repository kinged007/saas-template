import { resetSessionState } from "./storage.ts";

/**
 * Send a credential POST — login, register, 2FA verify, OAuth code exchange —
 * with the outgoing session's identity already torn down.
 *
 * The dataProvider's request interceptor reads `getActiveWorkspaceId()`
 * synchronously and falls back to the persisted selection and identity, so a
 * credential POST made before the reset goes out carrying the outgoing user's
 * X-Workspace-ID. Wrapping the send keeps that ordering true on every path:
 * there is no credential request that should be scoped to the session it
 * replaces. A failed sign-in therefore leaves no outgoing selection behind:
 * the access token is untouched, and `/login` sits behind `<Authenticated>`, so
 * a live session never renders the form.
 */
export async function postCredentials<T>(send: () => Promise<T>): Promise<T> {
  resetSessionState();
  return send();
}
