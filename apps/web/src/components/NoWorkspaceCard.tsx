import { PlusCircle } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * The zero-workspace state, shared by the two surfaces the workspace guard
 * cannot cover: the dashboard and the profile workspaces list.
 *
 * `single` is `single_workspace`, which makes /workspaces/create redirect home,
 * so the button would navigate nowhere and the copy must not promise it.
 */
export function NoWorkspaceCard({ single }: { single: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>No workspace yet</CardTitle>
        <CardDescription>
          {single
            ? "This deployment allows one workspace and it is created for you. Ask an administrator to add you to it."
            : "Create a workspace to get started with managing your team."}
        </CardDescription>
      </CardHeader>
      {!single && (
        <CardContent>
          <Link to="/workspaces/create">
            <Button>
              <PlusCircle className="mr-2 h-4 w-4" />
              Create workspace
            </Button>
          </Link>
        </CardContent>
      )}
    </Card>
  );
}