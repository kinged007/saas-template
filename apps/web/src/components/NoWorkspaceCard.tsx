import { PlusCircle } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** What a user who cannot create a workspace is told to do instead. */
export const ASK_AN_ADMIN = "Ask an administrator to add you to it.";

/**
 * The zero-workspace state, shared by the two surfaces the workspace guard
 * cannot cover: the dashboard and the profile workspaces list.
 *
 * `single` is `single_workspace`, which makes /workspaces/create redirect home,
 * so the button would navigate nowhere and the copy must not promise it. The
 * locked-out copy says nothing about who owns the workspace: the flag also
 * hides memberships outside the oldest workspace, so a member of a workspace
 * they simply cannot see must be told the same thing.
 */
export function NoWorkspaceCard({ single }: { single: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>No workspace yet</CardTitle>
        <CardDescription>
          {single
            ? `This deployment allows one workspace. ${ASK_AN_ADMIN}`
            : "Create a workspace to get started with managing your team."}
        </CardDescription>
      </CardHeader>
      {!single && (
        <CardContent>
          {/* asChild renders a single <a>; <Link><Button> nests a button in a
              link and costs a second tab stop. Not gated on useCan: the
              workspaces.create permission is workspace-scoped and resolves false
              here, while POST /workspaces checks no permission at all. */}
          <Button asChild>
            <Link to="/workspaces/create">
              <PlusCircle className="mr-2 h-4 w-4" />
              Create workspace
            </Link>
          </Button>
        </CardContent>
      )}
    </Card>
  );
}