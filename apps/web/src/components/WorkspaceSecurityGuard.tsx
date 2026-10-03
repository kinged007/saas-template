import { useSyncExternalStore, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import { useWorkspace } from "@/contexts/WorkspaceContext";
import type { Identity } from "@/types";

/** Where the 2FA setup flow lives. Mirrors the profile settings route. */
export const TWO_FACTOR_SETUP_PATH = "/settings/profile/security";

// The redirect is skipped on the pages that stay reachable without clearing
// the requirement: the 2FA setup flow itself (re-redirecting would loop) and
// the workspace settings shell, which holds the Security tab — where an admin
// who has no 2FA turns the requirement back off. The API route is exempt for
// the same reason (skip_workspace_security); exempting only the API would
// leave no way back. The shell is exempt because that is what the user menu's
// "Workspace Settings" entry lands on: exempting only the Security leaf would
// make the toggle reachable by URL but not by navigation.
//
// The backend refuses every other workspace-scoped call for this session
// anyway, so nothing beyond the settings shell is reachable by clicking.
const EXEMPT_PREFIXES = ["/settings/profile", "/settings/workspace"];

/**
 * Sends members to the 2FA setup flow when the active workspace requires 2FA
 * and this session never cleared it.
 *
 * The backend is the authority — it refuses workspace-scoped requests with
 * `2fa_required_for_workspace`. This guard only gets the user to the page that
 * fixes it, rather than leaving them on a page of failed requests.
 *
 * It reads the same per-session verdict the gate reads (`two_factor_verified`
 * on the workspace), so client and server cannot disagree and strand a user on
 * a page whose every request 403s.
 *
 * Reads the identity from the query cache rather than calling
 * `useGetIdentity`: react-query merges observer options onto the one shared
 * identity query, and an extra observer mounted above the routed content can
 * wedge it (see the note in WorkspaceContext). This is the same
 * cache-subscription pattern that provider uses.
 *
 * Takes the routed content as children and withholds it while the session is
 * blocked, rather than redirecting from an effect. A gated page must not mount
 * at all: pages that write the URL from their own mount effect (InboxPage
 * syncing its tab to the query string) re-assert the location after any
 * redirect and land the member on a page whose every request 403s.
 */
export function WorkspaceSecurityGuard({ children }: { children: ReactNode }) {
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

  if (!identity || !workspace) return <>{children}</>;
  if (!workspace.require_2fa || workspace.two_factor_verified) return <>{children}</>;
  if (EXEMPT_PREFIXES.some((prefix) => location.pathname.startsWith(prefix))) return <>{children}</>;

  return <Navigate to={TWO_FACTOR_SETUP_PATH} replace />;
}
