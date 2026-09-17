import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PlusCircle } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { WorkspaceSearch } from "@/components/WorkspaceSearch";
import { useWorkspace } from "../contexts/WorkspaceContext";

export function DashboardPage() {
  const { workspace } = useWorkspace();

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

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">{workspace?.name ?? "Workspace"}</h2>
        <p className="text-muted-foreground mt-1">
          Manage your team and collaborate effectively.
        </p>
      </div>

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
