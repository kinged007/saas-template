import { useLayoutEffect, useReducer, useRef } from "react";
import { useCan, useGetIdentity, useList } from "@refinedev/core";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CheckCircle2, Circle, PlusCircle, X } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { WorkspaceSearch } from "@/components/WorkspaceSearch";
import { useWorkspace } from "../contexts/WorkspaceContext";
import { onboardingStore } from "@/utils/storage";
import { IDENTITY_QUERY_OPTIONS } from "../contexts/WorkspaceContext";
import type { ApiKey, Identity, Invitation } from "../types";

function Step({ done, title, hint, to, cta }: { done: boolean; title: string; hint: string; to: string; cta: string }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <div className="flex items-start gap-3">
        {done ? (
          <CheckCircle2 className="mt-0.5 h-5 w-5 text-green-600" />
        ) : (
          <Circle className="mt-0.5 h-5 w-5 text-muted-foreground" />
        )}
        <div>
          <p className="font-medium">{title}</p>
          <p className="text-muted-foreground text-sm">{hint}</p>
        </div>
      </div>
      {!done && (
        <Link to={to}>
          <Button variant="outline" size="sm">{cta}</Button>
        </Link>
      )}
    </div>
  );
}

export function DashboardPage() {
  const { workspace } = useWorkspace();
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  // Dismissal is read from the store every render; force() only triggers a
  // re-render after dismiss. No dismissed state is kept, so switching
  // workspaces can never show a stale dismissal from another workspace.
  const [, force] = useReducer((x: number) => x + 1, 0);
  // Restoring unmounts the button while it holds focus, which drops focus to
  // <body> and tells a screen reader nothing. Move focus to the card heading
  // in the commit that brings the card back.
  const restoreHeading = useRef<HTMLDivElement>(null);
  const focusHeadingOnRender = useRef(false);
  useLayoutEffect(() => {
    if (!focusHeadingOnRender.current) return;
    focusHeadingOnRender.current = false;
    restoreHeading.current?.focus();
  });
  const onboardingDismissed = workspace
    ? onboardingStore.isDismissed(workspace.id, identity?.id)
    : false;
  // Workspace-wide switch (workspace:update): off hides the card for everyone,
  // including users who never dismissed it. A user's own dismissal is
  // deliberately not cleared when this is switched back on — it is their
  // choice, and the flag exists to control what new users are shown.
  const onboardingOffForWorkspace = workspace?.onboarding_enabled === false;
  const { data: canInvite } = useCan({ resource: "invitations", action: "create" });
  const { result: keysResult } = useList<ApiKey>({
    resource: "api-keys",
    queryOptions: { enabled: !!workspace },
  });
  const { result: invitationsResult } = useList<Invitation>({
    resource: "invitations",
    queryOptions: { enabled: !!workspace && !!canInvite?.can },
  });

  if (!workspace) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No workspace yet</CardTitle>
          <CardDescription>
            Create a workspace to get started with managing your team.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link to="/workspaces/create">
            <Button>
              <PlusCircle className="mr-2 h-4 w-4" />
              Create workspace
            </Button>
          </Link>
        </CardContent>
      </Card>
    );
  }

  const keys = keysResult?.data ?? [];
  const invitations = invitationsResult?.data ?? [];
  // ponytail: step progress is derived per render; only dismissal persists (onboardingStore). Add a tour store when onboarding grows past 3 steps.
  const steps = workspace
    ? [
        { done: invitations.length > 0, title: "Invite your team", hint: "Members get workspace access by role.", to: "/members", cta: "Invite" },
        { done: keys.length > 0, title: "Create an API key", hint: "Automate with scoped machine credentials.", to: "/api-keys/create", cta: "Create key" },
      ]
    : [];
  const allDone = steps.length > 0 && steps.every((s) => s.done);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">{workspace?.name ?? "Workspace"}</h2>
          <p className="text-muted-foreground mt-1">
            Manage your team and collaborate effectively.
          </p>
        </div>
        {/* The card is hidden by three independent reasons (all steps done, the
            caller's own dismissal, the workspace flag). Restore shows only
            when the caller's dismissal is the sole reason it is gone. */}
        {onboardingDismissed && !allDone && !onboardingOffForWorkspace && (
          <Button
            variant="ghost"
            size="sm"
            className="shrink-0"
            onClick={() => {
              if (workspace) onboardingStore.clear(workspace.id, identity?.id);
              focusHeadingOnRender.current = true;
              force();
            }}
          >
            Show setup checklist again
          </Button>
        )}
      </div>

      {!allDone && !onboardingDismissed && !onboardingOffForWorkspace && (
        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-2">
              <div>
                <CardTitle tabIndex={-1} ref={restoreHeading}>Get set up</CardTitle>
                <CardDescription>
                  {workspace ? "Finish these steps to get the most out of your workspace." : "Create a workspace to get started with managing your team."}
                </CardDescription>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                aria-label="Dismiss onboarding"
                disabled={!identity}
                onClick={() => {
                  if (workspace) onboardingStore.dismiss(workspace.id, identity?.id);
                  force();
                }}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="divide-y">
            {!workspace && (
              <Link to="/workspaces/create">
                <Button>
                  <PlusCircle className="mr-2 h-4 w-4" />
                  Create workspace
                </Button>
              </Link>
            )}
            {steps.map((s) => (
              <Step key={s.title} {...s} />
            ))}
          </CardContent>
        </Card>
      )}
      <WorkspaceSearch />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Members</CardTitle>
            <CardDescription>Manage workspace members and their roles</CardDescription>
          </CardHeader>
          <CardContent>
            <Link to="/members">
              <Button variant="outline">View Members</Button>
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Inbox</CardTitle>
            <CardDescription>View your notifications and updates</CardDescription>
          </CardHeader>
          <CardContent>
            <Link to="/inbox">
              <Button variant="outline">Open Inbox</Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
