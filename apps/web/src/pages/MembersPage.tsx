import { useEffect, useState } from "react";
import { useCan, useCreate, useCustomMutation, useGetIdentity, useInvalidate, useUpdate } from "@refinedev/core";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useWorkspaceList } from "../hooks/useWorkspaceQuery";

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
import { UserAvatar } from "@/components/ui/user-avatar";
import { UserProfileDialog } from "@/components/UserProfileDialog";

import { IDENTITY_QUERY_OPTIONS, useWorkspace } from "../contexts/WorkspaceContext";
import { canResendInvitation, canRevokeInvitation, invitationStatus } from "./invitation-actions";
import type { Identity, Invitation, Member, Role } from "../types";
import { getMemberDisplayName } from "../types";

const MANAGER_ROLES = ["owner", "admin"];

const PAGE_SIZE = 10;
// The role pickers need every role, ordered by the endpoint. Capped at one
// full page: past this the pickers drop the tail, and a pager is not worth it
// on a settings surface.
const ROLES_PAGE_SIZE = 100;

export function MembersPage() {
  const [selectedMember, setSelectedMember] = useState<Member | null>(null);
  const [membersPage, setMembersPage] = useState(1);
  const [invitesPage, setInvitesPage] = useState(1);
  const { workspace } = useWorkspace();
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  const { result: membersResult } = useWorkspaceList<Member>({
    resource: "members",
    pagination: { currentPage: membersPage, pageSize: PAGE_SIZE },
    sorters: [{ field: "created_at", order: "desc" }],
  });
  const { result: rolesResult } = useWorkspaceList<Role>({
    resource: "roles",
    pagination: { currentPage: 1, pageSize: ROLES_PAGE_SIZE },
  });
  const { data: canManage } = useCan({ resource: "members", action: "edit" });
  const { data: canDelete } = useCan({ resource: "members", action: "delete" });
  // The invitations section is gated on invitations:create, not on the invite
  // button alone: GET /invitations requires MEMBER_CREATE (invitations.py:64).
  // A role holding member:delete without member:create therefore gets no section,
  // which leaves the canRevoke gate below unreachable for it.
  const { data: canInvite } = useCan({ resource: "invitations", action: "create" });
  const { data: canRevoke } = useCan({ resource: "invitations", action: "delete" });
  const { result: invitationsResult } = useWorkspaceList<Invitation>({
    resource: "invitations",
    pagination: { currentPage: invitesPage, pageSize: PAGE_SIZE },
    sorters: [{ field: "created_at", order: "desc" }],
    queryOptions: { enabled: !!canInvite?.can },
  });
  const { mutate: changeRole } = useUpdate();
  const { mutate: invite, mutation } = useCreate();
  const { mutate: resend } = useCustomMutation();
  const invalidate = useInvalidate();
  const refreshInvitations = () => invalidate({ resource: "invitations", invalidates: ["list"] });
  const [email, setEmail] = useState("");
  const [inviteRoleId, setInviteRoleId] = useState("");

  const rows = membersResult?.data ?? [];
  const membersTotal = membersResult?.total ?? 0;
  const membersTotalPages = Math.max(1, Math.ceil(membersTotal / PAGE_SIZE));
  const roleOptions = rolesResult?.data ?? [];
  const invitations = invitationsResult?.data ?? [];
  const invitesTotal = invitationsResult?.total ?? 0;
  const invitesTotalPages = Math.max(1, Math.ceil(invitesTotal / PAGE_SIZE));
  const assignableRoles = roleOptions.filter((r) => r.name !== "owner");

  useEffect(() => {
    if (membersPage > membersTotalPages) setMembersPage(membersTotalPages);
  }, [membersPage, membersTotalPages]);
  useEffect(() => {
    if (invitesPage > invitesTotalPages) setInvitesPage(invitesTotalPages);
  }, [invitesPage, invitesTotalPages]);

  const myRole = identity?.workspaces.find((w) => w.id === workspace?.id)?.role;
  const canManageRoles = !!canManage?.can && MANAGER_ROLES.includes(myRole ?? "");
  const { mutate: memberAction } = useCustomMutation();

  const suspend = (m: Member, suspendIt: boolean) => {
    memberAction(
      {
        url: `members/${m.membership_id}/${suspendIt ? "suspend" : "reactivate"}`,
        method: "post",
        values: {},
        successNotification: { message: suspendIt ? "Member suspended" : "Member reactivated", type: "success" },
      },
      { onSuccess: () => invalidate({ resource: "members", invalidates: ["list"] }) },
    );
  };

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
          setInvitesPage(1);
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
              <TableHead>Status</TableHead>
              <TableHead>Joined</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((m) => {
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
                        onClick={() => setSelectedMember(m)}
                      />
                      <div className="flex flex-col">
                        <p className="font-medium">{name}</p>
                        <p className="text-muted-foreground text-xs">{m.email}</p>
                      </div>
                    </div>
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
                        <SelectValue>
                          {assignableRoles.find((r) => r.id === m.role_id)?.name ?? m.role}
                        </SelectValue>
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
                <TableCell>
                  <StatusBadge status={m.status} />
                </TableCell>
                <TableCell className="text-muted-foreground">{formatDate(m.joined_at)}</TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-1">
                    {canManageRoles && m.role !== "owner" && m.status !== "suspended" && (
                      <Button variant="ghost" size="sm" onClick={() => suspend(m, true)}>
                        Suspend
                      </Button>
                    )}
                    {canManageRoles && m.status === "suspended" && (
                      <Button variant="ghost" size="sm" onClick={() => suspend(m, false)}>
                        Reactivate
                      </Button>
                    )}
                    {canDelete?.can && m.role !== "owner" && (
                      <DeleteButton
                        resource="members"
                        recordItemId={m.membership_id}
                        variant="ghost"
                        size="sm"
                      />
                    )}
                  </div>
                </TableCell>
              </TableRow>
              );
            })}
            {rows.length === 0 && <EmptyRow colSpan={6}>No members yet.</EmptyRow>}
          </TableBody>
        </Table>
      </div>
      {membersTotal > PAGE_SIZE && (
      <div className="flex items-center justify-between gap-2">
        <p className="text-muted-foreground text-sm">
          Showing {(membersPage - 1) * PAGE_SIZE + 1}–{Math.min(membersPage * PAGE_SIZE, membersTotal)} of {membersTotal}
        </p>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            disabled={membersPage <= 1}
            onClick={() => setMembersPage((c) => Math.max(1, c - 1))}
          >
            <ChevronLeft className="h-4 w-4" />
            Previous
          </Button>
          <span className="text-muted-foreground px-2 text-sm">
            Page {membersPage} of {membersTotalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={membersPage >= membersTotalPages}
            onClick={() => setMembersPage((c) => Math.min(membersTotalPages, c + 1))}
          >
            Next
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
      )}

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
                  <SelectValue placeholder="Role">{roleName(inviteRoleId)}</SelectValue>
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
                      <StatusBadge status={invitationStatus(i)} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">{formatDate(i.expires_at)}</TableCell>
                    <TableCell className="text-muted-foreground">{formatDate(i.created_at)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        {canRevoke?.can && canRevokeInvitation(i) && (
                          <DeleteButton
                            resource="invitations"
                            recordItemId={i.id}
                            variant="ghost"
                            size="sm"
                          />
                        )}
                        {canResendInvitation(i) && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              resend(
                                {
                                  url: `invitations/${i.id}/resend`,
                                  method: "post",
                                  values: {},
                                  successNotification: { message: "Invitation re-sent", type: "success" },
                                },
                                {
                                  // A 409 means the server already made the invitation
                                  // terminal, so the cached row is stale either way.
                                  onSuccess: refreshInvitations,
                                  onError: refreshInvitations,
                                },
                              )
                            }
                          >
                            Re-send
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
                {invitations.length === 0 && <EmptyRow colSpan={6}>No invitations yet.</EmptyRow>}
              </TableBody>
            </Table>
          </div>
          {invitesTotal > PAGE_SIZE && (
          <div className="flex items-center justify-between gap-2">
            <p className="text-muted-foreground text-sm">
              Showing {(invitesPage - 1) * PAGE_SIZE + 1}–{Math.min(invitesPage * PAGE_SIZE, invitesTotal)} of {invitesTotal}
            </p>
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                disabled={invitesPage <= 1}
                onClick={() => setInvitesPage((c) => Math.max(1, c - 1))}
              >
                <ChevronLeft className="h-4 w-4" />
                Previous
              </Button>
              <span className="text-muted-foreground px-2 text-sm">
                Page {invitesPage} of {invitesTotalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={invitesPage >= invitesTotalPages}
                onClick={() => setInvitesPage((c) => Math.min(invitesTotalPages, c + 1))}
              >
                Next
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
          )}
        </section>
      )}
      <UserProfileDialog
        userId={selectedMember?.id ?? null}
        open={!!selectedMember}
        onOpenChange={(open) => {
          if (!open) setSelectedMember(null);
        }}
        fallback={
          selectedMember
            ? {
                display_name: getMemberDisplayName(selectedMember),
                email: selectedMember.email,
                avatar_url: selectedMember.avatar_url,
                first_name: selectedMember.first_name,
                last_name: selectedMember.last_name,
              }
            : undefined
        }
      />
    </ListView>
  );
}
