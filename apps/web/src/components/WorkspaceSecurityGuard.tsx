import { useSyncExternalStore } from "react";
import { Navigate, useLocation } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import { useWorkspace } from "@/contexts/WorkspaceContext";
import type { Identity } from "@/types";

/** Where the 2FA setup flow lives. Mirrors the profile settings route. */
export const TWO_FACTOR_SETUP_PATH = "/settings/profile/security";

// The redirect is skipped while the user is already anywhere under profile
// settings: that is where they land, and re-redirecting would loop.
const EXEMPT_PREFIX = "/settings/profile";

/**
 * Sends members to the 2FA setup flow when the active workspace requires 2FA
 * and they have not enabled it.
 *
 * The backend is the authority — it refuses workspace-scoped requests with
 * `2fa_required_for_workspace`. This guard only gets the user to the page that
 * fixes it, rather than leaving them on a page of failed requests.
 *
 * Reads the identity from the query cache rather than calling
 * `useGetIdentity`: react-query merges observer options onto the one shared
 * identity query, and an extra observer mounted above the routed content can
 * wedge it (see the note in WorkspaceContext). This is the same
 * cache-subscription pattern that provider uses.
 */
export function WorkspaceSecurityGuard() {
  const { workspace } = useWorkspace();
  const queryClient = useQueryClient();
  const location = useLocation();

  // Subscribing means a later identity refetch (e.g. an admin flipping the
  // setting) re-renders this guard; a one-shot getQueryData would not.
  const identity = useSyncExternalStore(
    (onChange) => queryClient.getQueryCache().subscribe(onChange),
    () => queryClient.getQueryData<Identity>(["auth", "identity"]),
    () => undefined,
  );

  if (!identity || !workspace) return null;
  if (!workspace.require_2fa || workspace.two_factor_enabled) return null;
  if (location.pathname.startsWith(EXEMPT_PREFIX)) return null;

  return <Navigate to={TWO_FACTOR_SETUP_PATH} replace />;
}
