import { useState } from "react";
import { useCustomMutation, useGetIdentity } from "@refinedev/core";
import { Link } from "react-router";
import { toast } from "sonner";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useWorkspace, IDENTITY_QUERY_OPTIONS } from "@/contexts/WorkspaceContext";
import { TWO_FACTOR_SETUP_PATH } from "@/components/WorkspaceSecurityGuard";
import type { Identity } from "@/types";

/**
 * Workspace security settings.
 *
 * One setting today: require 2FA. When it is on, members whose session never
 * cleared a 2FA check are refused on workspace-scoped requests and redirected
 * to the profile security page to set it up.
 */
export function SecuritySection() {
  const { workspace, refresh } = useWorkspace();
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  const { mutate, mutation } = useCustomMutation();
  const [pending, setPending] = useState<boolean | null>(null);

  if (!workspace) {
    return <p className="text-muted-foreground text-sm">No workspace selected.</p>;
  }

  const required = workspace.require_2fa === true;
  // `pending` keeps the checkbox responsive before the refetch lands; null
  // means "follow the server value".
  const checked = pending ?? required;
  const saving = mutation.isPending;

  const me = identity?.workspaces.find((w) => w.id === workspace.id);
  // Per-session verdict, the same one the backend gate reads.
  const sessionVerified = me?.two_factor_verified === true;

  const setRequired = (value: boolean) => {
    setPending(value);
    mutate(
      {
        url: `workspaces/${workspace.id}/security`,
        method: "patch",
        values: { require_2fa: value },
        successNotification: false,
        errorNotification: false,
      },
      {
        onSuccess: () => {
          setPending(null);
          toast.success(
            value ? "Members must now use two-factor authentication" : "Two-factor requirement removed",
          );
          refresh();
        },
        onError: (err: unknown) => {
          setPending(null);
          toast.error((err as { message?: string })?.message || "Failed to update security settings");
        },
      },
    );
  };

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Two-factor authentication</CardTitle>
          <CardDescription>
            Require every member to use an authenticator app when signing in.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <label className="flex cursor-pointer items-start gap-3">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-primary"
              checked={checked}
              disabled={saving}
              onChange={(e) => setRequired(e.target.checked)}
            />
            <span className="flex flex-col gap-1">
              <span className="text-sm font-medium">Require two-factor authentication</span>
              <span className="text-muted-foreground text-sm">
                Members whose session has not cleared an authenticator-app check are sent to
                their profile security page to set one up, and cannot use workspace features
                until they do.
              </span>
            </span>
          </label>

          {required && !sessionVerified && (
            <p className="text-muted-foreground rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
              This requirement is on and your own session has not cleared two-factor
              authentication. Other members are unaffected, but your own workspace access stays
              limited until you{" "}
              <Link className="underline" to={TWO_FACTOR_SETUP_PATH}>
                set it up
              </Link>
              . You can turn the requirement off again at any time from this page.
            </p>
          )}

          {sessionVerified && (
            <p className="text-muted-foreground text-sm">
              Your own session has cleared two-factor authentication.{" "}
              <Link className="underline" to={TWO_FACTOR_SETUP_PATH}>
                Manage it in your profile
              </Link>
              .
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>How this is enforced</CardTitle>
          <CardDescription>Where the requirement is applied.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <div className="flex justify-between border-b py-2">
            <span className="text-muted-foreground">Applies to</span>
            <span>Members signing in with a password</span>
          </div>
          <div className="flex justify-between border-b py-2">
            <span className="text-muted-foreground">Checked on</span>
            <span>Every workspace-scoped HTTP request</span>
          </div>
          <div className="flex justify-between py-2">
            <span className="text-muted-foreground">API keys</span>
            <span>Not affected</span>
          </div>
          <p className="text-muted-foreground text-xs">
            API keys are server-side credentials with their own permission list and no
            authenticator app, so they are exempt. Keys issued before this setting was turned on
            keep working. The live notification socket is user-scoped rather than
            workspace-scoped, so it stays open for members this setting refuses.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
