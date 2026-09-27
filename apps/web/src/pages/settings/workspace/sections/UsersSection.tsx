import {  } from "@refinedev/core";
import { useWorkspaceList } from "../../../../hooks/useWorkspaceQuery";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyRow, formatDate } from "@/components/ui";
import { UserAvatar } from "@/components/ui/user-avatar";
import type { Member } from "@/types";
import { getMemberDisplayName } from "@/types";

export function UsersSection() {
  const { result, query } = useWorkspaceList<Member>({ resource: "members" });
  const rows = result?.data ?? [];
  const isLoading = query.isPending;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Users</CardTitle>
          <CardDescription>
            General user settings for this workspace. Manage defaults and view membership.
            {__DEV_NOTES__ && (
              <>
                {" "}This section is intentionally minimal — extend it in{" "}
                <code>apps/web/src/pages/settings/workspace/sections/UsersSection.tsx</code> or add new sections via the
                settings registry.
              </>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="rounded-lg border p-4">
            <h4 className="font-medium">Workspace users</h4>
            <p className="text-muted-foreground text-sm">
              Full member management (roles, invites, removal) lives on the Members page. This overview is read-only.
            </p>
            <div className="mt-4 overflow-x-auto rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>User</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Joined</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {isLoading ? (
                    <EmptyRow colSpan={4}>Loading…</EmptyRow>
                  ) : (
                    rows.map((m) => {
                      const name = getMemberDisplayName(m);
                      return (
                        <TableRow key={m.membership_id}>
                          <TableCell>
                            <div className="flex items-center gap-3">
                              <UserAvatar
                                name={name}
                                email={m.email}
                                avatarUrl={m.avatar_url}
                                sizeClassName="h-8 w-8"
                                fallbackClassName="text-xs"
                                firstName={m.first_name}
                                lastName={m.last_name}
                              />
                              <div className="flex flex-col">
                                <span className="font-medium">{name}</span>
                                <span className="text-muted-foreground text-xs">{m.email}</span>
                              </div>
                            </div>
                          </TableCell>
                          <TableCell>{m.role}</TableCell>
                          <TableCell className="capitalize">{m.status}</TableCell>
                          <TableCell className="text-muted-foreground">{formatDate(m.joined_at)}</TableCell>
                        </TableRow>
                      );
                    })
                  )}
                  {!isLoading && rows.length === 0 && <EmptyRow colSpan={4}>No members yet.</EmptyRow>}
                </TableBody>
              </Table>
            </div>
          </div>

          {__DEV_NOTES__ && (
            <div className="rounded-lg border border-dashed p-4">
              <h4 className="font-medium">Extension point</h4>
              <p className="text-muted-foreground text-sm">
                Add workspace-wide user defaults (e.g. default invite role, allowed domains) here. Register additional
                tabs via <code>workspaceSettings.register()</code> in <code>registry.ts</code> to keep this file small.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
