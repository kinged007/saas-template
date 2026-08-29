import { useState } from "react";
import { useCan, useCreate, useGetIdentity, useList, useUpdate } from "@refinedev/core";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DeleteButton } from "../components/refine-ui/buttons/delete";
import { ListView, ListViewHeader } from "../components/refine-ui/views/list-view";
import { EmptyRow, StatusBadge, formatDate } from "../components/ui";
import { IDENTITY_QUERY_OPTIONS, useWorkspace } from "../contexts/WorkspaceContext";
import type { Identity, Invitation, Member, Role } from "../types";

const MANAGER_ROLES = ["owner", "admin"];

export function MembersPage() {
  const { workspace } = useWorkspace();
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  const { result: membersResult } = useList<Member>({ resource: "members" });
  const { result: rolesResult } = useList<Role>({ resource: "roles" });
  const { data: canManage } = useCan({ resource: "members", action: "edit" });
  const { data: canDelete } = useCan({ resource: "members", action: "delete" });
  const { data: canInvite } = useCan({ resource: "invitations", action: "create" });
  const { result: invitationsResult } = useList<Invitation>({
    resource: "invitations",
    queryOptions: { enabled: !!canInvite?.can },
  });
  const { mutate: changeRole } = useUpdate();
  const { mutate: invite, mutation } = useCreate();
  const [email, setEmail] = useState("");
  const [inviteRoleId, setInviteRoleId] = useState("");

  const rows = membersResult?.data ?? [];
  const roleOptions = rolesResult?.data ?? [];
  const invitations = invitationsResult?.data ?? [];
  const assignableRoles = roleOptions.filter((r) => r.name !== "owner");

  const myRole = identity?.workspaces.find((w) => w.id === workspace?.id)?.role;
  const canManageRoles = !!canManage?.can && MANAGER_ROLES.includes(myRole ?? "");
  const roleName = (roleId: string) => roleOptions.find((r) => r.id === roleId)?.name;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !inviteRoleId) return;
    invite(
      {
        resource: "invitations",
        values: { email, role_id: inviteRoleId },
        successNotification: { message: "Invitation sent", type: "success" },
      },
      {
        onSuccess: () => {
          setEmail("");
          setInviteRoleId("");
        },
      },
    );
  };

  return (
    <ListView>
      <ListViewHeader title="Members" canCreate={false} />
      <div className="border-border overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Change role</TableHead>
              <TableHead>Joined</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((m) => (
              <TableRow key={m.membership_id}>
                <TableCell>
                  <p className="font-medium">{m.display_name}</p>
                  <p className="text-muted-foreground text-xs">{m.email}</p>
                </TableCell>
                <TableCell>{m.role}</TableCell>
                <TableCell>
                  {canManageRoles && m.role !== "owner" ? (
                    <Select
                      value={m.role_id}
                      onValueChange={(roleId) =>
                        changeRole({
                          resource: "members",
                          id: m.membership_id,
                          values: { role_id: roleId },
                          successNotification: { message: "Role updated", type: "success" },
                        })
                      }
                    >
                      <SelectTrigger className="w-36">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {assignableRoles.map((r) => (
                          <SelectItem key={r.id} value={r.id}>
                            {r.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground">{formatDate(m.joined_at)}</TableCell>
                <TableCell className="text-right">
                  {canDelete?.can && m.role !== "owner" && (
                    <DeleteButton
                      resource="members"
                      recordItemId={m.membership_id}
                      variant="ghost"
                      size="sm"
                    />
                  )}
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && <EmptyRow colSpan={5}>No members yet.</EmptyRow>}
          </TableBody>
        </Table>
      </div>

      {canInvite?.can && (
        <section className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h3 className="text-lg font-semibold">Invited members</h3>
            <p className="text-muted-foreground text-sm">
              Invitations sent to join this workspace.
            </p>
          </div>
          <form
            onSubmit={submit}
            className="border-border flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-end"
          >
            <div className="flex flex-1 flex-col gap-2">
              <Label htmlFor="invite-email">Email</Label>
              <Input
                id="invite-email"
                placeholder="person@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label>Role</Label>
              <Select value={inviteRoleId} onValueChange={setInviteRoleId}>
                <SelectTrigger className="w-40">
                  <SelectValue placeholder="Role" />
                </SelectTrigger>
                <SelectContent>
                  {assignableRoles.map((r) => (
                    <SelectItem key={r.id} value={r.id}>
                      {r.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button type="submit" disabled={mutation.isPending || !email.trim() || !inviteRoleId}>
              {mutation.isPending ? "Sending…" : "Invite"}
            </Button>
          </form>
          <div className="border-border overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Expires</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {invitations.map((i) => (
                  <TableRow key={i.id}>
                    <TableCell>{i.email}</TableCell>
                    <TableCell>{roleName(i.role_id) ?? "—"}</TableCell>
                    <TableCell>
                      <StatusBadge status={i.status} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">{formatDate(i.expires_at)}</TableCell>
                    <TableCell className="text-muted-foreground">{formatDate(i.created_at)}</TableCell>
                    <TableCell className="text-right">
                      {i.status === "pending" && (
                        <DeleteButton
                          resource="invitations"
                          recordItemId={i.id}
                          variant="ghost"
                          size="sm"
                        />
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {invitations.length === 0 && <EmptyRow colSpan={6}>No invitations yet.</EmptyRow>}
              </TableBody>
            </Table>
          </div>
        </section>
      )}
    </ListView>
  );
}
