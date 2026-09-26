import { useCan, useList } from "@refinedev/core";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CheckCircle2, Circle, PlusCircle } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { useWorkspace } from "../contexts/WorkspaceContext";
import type { ApiKey, Invitation } from "../types";

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
  // ponytail: progress is derived per render (no persistence); add a dismissible tour store when onboarding grows past 3 steps.
  const steps = workspace
    ? [
        { done: invitations.length > 0, title: "Invite your team", hint: "Members get workspace access by role.", to: "/members", cta: "Invite" },
        { done: keys.length > 0, title: "Create an API key", hint: "Automate with scoped machine credentials.", to: "/api-keys/create", cta: "Create key" },
      ]
    : [];
  const allDone = steps.length > 0 && steps.every((s) => s.done);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">{workspace?.name ?? "Workspace"}</h2>
        <p className="text-muted-foreground mt-1">
          Manage your team and collaborate effectively.
        </p>
      </div>

      {!allDone && (
        <Card>
          <CardHeader>
            <CardTitle>Get set up</CardTitle>
            <CardDescription>
              {workspace ? "Finish these steps to get the most out of your workspace." : "Create a workspace to get started with managing your team."}
            </CardDescription>
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
