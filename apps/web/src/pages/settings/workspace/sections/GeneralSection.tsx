import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { toast } from "sonner";
import { useCan, useCustomMutation, useDelete, useGetIdentity, useInvalidate, useNavigation } from "@refinedev/core";
import { Link, useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  FormDescription,
} from "@/components/ui/form";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import { IDENTITY_QUERY_OPTIONS } from "@/contexts/WorkspaceContext";
import { useWorkspaceList } from "@/hooks/useWorkspaceQuery";
import type { Identity, Member } from "@/types";
import { getDisplayNameFromRow, memberOptionLabel } from "@/types";
import { WorkspaceExportCard } from "@/components/WorkspaceExportCard";
import { workspaceStore } from "@/utils/storage";
import { resolveTransferTarget, transferCandidateMessage, transferCapNotice, transferEligibleMembers } from "./transfer-ownership";
import { isOwnerRoleName } from "@/pages/role-name";

// One picker on the page, so one id: aria-describedby resolves to the element
// carrying it, and a second picker would need a second paragraph.
const TRANSFER_CAP_ID = "transfer-cap";

// parse_query in apps/api/src/api/crud.py clamps with max_limit=100, so this is
// the largest page /members returns. A longer workspace is disclosed by the cap
// notice, not paginated through.
const MEMBERS_PAGE_SIZE = 100;

const schema = z.object({
  name: z.string().min(1, "Name is required").max(150, "Max 150 characters"),
  description: z.string().max(500, "Max 500 characters").optional().or(z.literal("")),
});

type FormData = z.infer<typeof schema>;

export function GeneralSection() {
  const { workspace, refresh } = useWorkspace();
  const navigate = useNavigate();
  const { mutate, mutation } = useCustomMutation();
  const isSaving = mutation.isPending;
  const { data: canDelete } = useCan({ resource: "workspaces", action: "delete" });
  // workspace:update is held by owners and admins, so both can run this toggle.
  // "edit" is the mapped action for that permission; an unmapped action makes
  // accessControlProvider fall through to `{ can: true }` for everyone.
  const { data: canUpdate } = useCan({ resource: "workspaces", action: "edit" });
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  // SINGLE_WORKSPACE: the one shared workspace can never be deleted.
  const singleWorkspace = identity?.single_workspace === true;
  const { mutate: deleteWorkspace, mutation: deleteMutation } = useDelete();
  const isDeleting = deleteMutation.isPending;
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");

  const { mutate: transfer, mutation: transferMutation } = useCustomMutation();
  const { result: membersResult, query: membersQuery } = useWorkspaceList<Member>({
    resource: "members",
    pagination: { pageSize: MEMBERS_PAGE_SIZE },
  });
  const invalidate = useInvalidate();
  const [transferId, setTransferId] = useState("");
  const [transferOpen, setTransferOpen] = useState(false);
  const isOwner = isOwnerRoleName(workspace?.role);
  const members = membersResult?.data ?? [];
  const transferCandidates = transferEligibleMembers(members);
  const transferCap = transferCapNotice(membersResult?.total ?? 0, members);
  // A transferId that stopped resolving on a refetch leaves transferTarget
  // undefined, which is what disarms the button below.
  // SelectValue without children renders the placeholder forever, so the trigger
  // needs the picked member as its own text — the same label the options render
  // via memberOptionLabel.
  const transferTarget = resolveTransferTarget(transferCandidates, transferId);
  const transferTargetName = transferTarget ? getDisplayNameFromRow(transferTarget) : "";
  const transferTargetLabel = transferTarget ? memberOptionLabel(transferTarget) : "";
  // The members endpoint clamps `limit` to 100 and orders by created_at desc,
  // so this page holds the newest rows and the rows it drops are the oldest
  // ones. The notice says both and links the member table, which pages through
  // every candidate `transfer_ownership` accepts.
  // ponytail: the picker itself is still one page; page the select if a
  // workspace above 100 members makes hunting an owner the common case.
  const membersTruncated = (membersResult?.total ?? 0) > members.length;
  const { listUrl } = useNavigation();
  const candidatesMessage = transferCandidateMessage({
    isPending: membersQuery.isPending,
    isError: membersQuery.isError,
    loaded: members.length,
    total: membersResult?.total ?? 0,
  });

  // Drop a stale id so the trigger shows the placeholder again: an id that names
  // no item renders as an empty box rather than the placeholder. The dialog
  // closes with it — DialogContent is conditional on the target, so leaving
  // transferOpen true would strand an open dialog with nothing mounted.
  useEffect(() => {
    if (transferId && !transferTarget) {
      setTransferId("");
      setTransferOpen(false);
    }
  }, [transferId, transferTarget]);

  const transferOwnership = () => {
    if (!workspace || !transferTarget) return;
    transfer(
      {
        url: `workspaces/${workspace.id}/transfer`,
        method: "post",
        values: { new_owner_membership_id: transferTarget.membership_id },
        successNotification: false,
        errorNotification: false,
      },
      {
        onSuccess: () => {
          toast.success("Ownership transferred", {
            description: "You are now an admin of this workspace.",
          });
          setTransferId("");
          setTransferOpen(false);
          // Identity carries the role and permissions the UI gates on, and the
          // shared identity query is stale for 30s — refetch it explicitly.
          refresh();
          void invalidate({ resource: "members", invalidates: ["list"] });
        },
        onError: (err: unknown) => {
          toast.error(
            (err as { message?: string })?.message || "Failed to transfer ownership",
          );
        },
      },
    );
  };

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", description: "" },
  });

  useEffect(() => {
    if (workspace) {
      form.reset({
        name: workspace.name ?? "",
        description: workspace.description ?? "",
      });
    }
  }, [workspace, form]);

  const onSubmit = (data: FormData) => {
    if (!workspace) return;
    mutate(
      {
        url: `workspaces/${workspace.id}`,
        method: "patch",
        values: {
          name: data.name,
          description: data.description || null,
        },
        successNotification: false,
        errorNotification: false,
      },
      {
        onSuccess: () => {
          toast.success("Workspace updated");
          refresh();
        },
        onError: (err: unknown) => {
          const msg = (err as { message?: string })?.message || "Failed to update workspace";
          toast.error(msg);
        },
      },
    );
  };

  // Toggles immediately on change so the switch never waits on a Save click.
  const setOnboardingEnabled = (enabled: boolean) => {
    if (!workspace) return;
    mutate(
      {
        url: `workspaces/${workspace.id}`,
        method: "patch",
        values: { onboarding_enabled: enabled },
        successNotification: false,
        errorNotification: false,
      },
      {
        onSuccess: () => {
          toast.success(enabled ? "Onboarding card shown" : "Onboarding card hidden");
          refresh();
        },
        onError: (err: unknown) => {
          const msg = (err as { message?: string })?.message || "Failed to update onboarding setting";
          toast.error(msg);
        },
      },
    );
  };

  if (!workspace) {
    return <p className="text-muted-foreground text-sm">No workspace selected.</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>General</CardTitle>
          <CardDescription>Update your workspace name and description.</CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input placeholder="My workspace" {...field} />
                    </FormControl>
                    <FormDescription>Visible to all members.</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Description</FormLabel>
                    <FormControl>
                      <Textarea placeholder="What is this workspace for?" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <div className="flex justify-end gap-2 pt-2">
                <Button type="submit" disabled={isSaving}>
                  {isSaving ? "Saving…" : "Save changes"}
                </Button>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Onboarding</CardTitle>
          <CardDescription>
            Show the “Get set up” card on the dashboard for this workspace.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-between gap-4">
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 accent-primary"
              checked={workspace.onboarding_enabled !== false}
              disabled={isSaving || !canUpdate?.can}
              onChange={(e) => setOnboardingEnabled(e.target.checked)}
            />
            Show onboarding card
          </label>
          {!canUpdate?.can && (
            <p className="text-muted-foreground text-xs">You need owner or admin permission.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Details</CardTitle>
          <CardDescription>Read-only workspace metadata.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <div className="flex justify-between border-b py-2">
            <span className="text-muted-foreground">Slug</span>
            <span className="font-mono">{workspace.slug}</span>
          </div>
          <div className="flex justify-between border-b py-2">
            <span className="text-muted-foreground">ID</span>
            <span className="font-mono text-xs">{workspace.id}</span>
          </div>
          {workspace.created_at && (
            <div className="flex justify-between py-2">
              <span className="text-muted-foreground">Created</span>
              <span>{new Date(workspace.created_at).toLocaleString()}</span>
            </div>
          )}
        </CardContent>
      </Card>

      <WorkspaceExportCard />

      {!singleWorkspace && (
        <>
          <Separator />
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 flex flex-col gap-4">
            <div>
              <h4 className="font-semibold text-destructive">Danger zone</h4>
              <p className="text-muted-foreground mt-1 text-sm">
                Deleting a workspace is permanent and irreversible.
              </p>
            </div>

            {isOwner && (
              <div className="grid grid-cols-1 gap-3 border-t border-destructive/30 pt-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
                <div>
                  <h4 className="font-semibold text-destructive">Transfer ownership</h4>
                  <p className="text-muted-foreground mt-1 text-sm">
                    Hand this workspace to another active member. You are demoted to admin — only the new
                    owner can transfer it back; the system will not reverse it for you. Requires an
                    interactive session: API keys cannot transfer ownership.
                  </p>
                </div>
                {transferCandidates.length > 0 && (
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="transfer-member">New owner</Label>
                    <Select value={transferId} onValueChange={setTransferId}>
                      <SelectTrigger
                        id="transfer-member"
                        className="w-full sm:w-72"
                        aria-describedby={transferCap ? TRANSFER_CAP_ID : undefined}
                      >
                        <SelectValue placeholder="Select member">{transferTargetLabel}</SelectValue>
                      </SelectTrigger>
                      <SelectContent>
                        {transferCandidates.map((m) => (
                          <SelectItem key={m.membership_id} value={m.membership_id}>
                            {memberOptionLabel(m)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {transferCap && (
                      <p id={TRANSFER_CAP_ID} className="text-muted-foreground text-sm">{transferCap}</p>
                    )}
                    <Dialog open={transferOpen} onOpenChange={setTransferOpen}>
                      <DialogTrigger asChild>
                        <Button variant="destructive" disabled={!transferTarget || transferMutation.isPending}>
                          Transfer ownership
                        </Button>
                      </DialogTrigger>
                      {/* No target left: the pick stopped resolving on a refetch, so there
                          is nothing to confirm and no name to state. Nothing renders. */}
                      {transferTarget && (
                        <DialogContent>
                          <DialogHeader>
                            <DialogTitle>Transfer ownership to {transferTargetName}?</DialogTitle>
                            <DialogDescription>
                              <span className="font-semibold">{workspace.name}</span> will be owned by{" "}
                              <span className="font-semibold">{transferTargetName}</span> ({transferTarget.email}).
                              You are demoted to admin immediately, and only the new owner can transfer it back. This
                              cannot be undone.
                            </DialogDescription>
                          </DialogHeader>
                          <DialogFooter>
                            <Button
                              variant="outline"
                              onClick={() => setTransferOpen(false)}
                              disabled={transferMutation.isPending}
                            >
                              Cancel
                            </Button>
                            <Button
                              variant="destructive"
                              onClick={transferOwnership}
                              disabled={transferMutation.isPending}
                            >
                              {transferMutation.isPending ? "Transferring…" : "Transfer ownership"}
                            </Button>
                          </DialogFooter>
                        </DialogContent>
                      )}
                    </Dialog>
                  </div>
                )}
                {/* Both notes span the full grid width. In the auto track their
                    max-content width wins the container and collapses the text
                    column to 0px, so the heading wraps one word per line. */}
                {transferCandidates.length === 0 && (
                  <p className="text-muted-foreground text-sm sm:col-span-2">{candidatesMessage}</p>
                )}
                {membersTruncated && (
                  <p className="text-muted-foreground text-xs sm:col-span-2">
                    Showing the first {members.length} of {membersResult?.total} members. Members beyond the first{" "}
                    {members.length} are not listed here — the list is newest first, so those are the oldest members.
                    Any other active member can take the transfer.{" "}
                    <Link className="underline" to={listUrl("members")}>
                      See all members
                    </Link>
                  </p>
                )}
              </div>
            )}

            <div className="grid grid-cols-1 gap-3 border-t border-destructive/30 pt-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
              <div>
                <h4 className="font-semibold text-destructive">Delete workspace</h4>
                <p className="text-muted-foreground mt-1 text-sm">
                  Deleting a workspace is <span className="font-semibold">permanent and irreversible</span>. The
                  workspace and all its scoped data will be removed: members, roles, invitations, API keys, scheduled
                  jobs and run history, conversations and messages, notifications, and stored secrets. User accounts
                  themselves are global and are not deleted — members simply lose access to this workspace. Audit log
                  entries are retained for compliance.
                </p>
                <p className="text-muted-foreground mt-2 text-sm">
                  This action is gated on <code>workspace:delete</code> (owners only). Admins, editors and viewers cannot
                  delete workspaces.
                </p>
              </div>
              <div className="flex flex-col gap-2">
                <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
                  <DialogTrigger asChild>
                    <Button variant="destructive" disabled={!canDelete?.can}>
                      Delete workspace
                    </Button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>Delete workspace “{workspace.name}”?</DialogTitle>
                      <DialogDescription>
                        This will permanently delete <span className="font-semibold">{workspace.name}</span> (
                        <code>{workspace.slug}</code>) and all workspace-scoped data listed in this section. Users who
                        were members will remain in the system but will no longer have access to this workspace. This cannot
                        be undone.
                      </DialogDescription>
                    </DialogHeader>
                    <div className="flex flex-col gap-3 py-2">
                      <Label htmlFor="confirm-name">
                        Type <code className="font-semibold">{workspace.name}</code> to confirm
                      </Label>
                      <Input
                        id="confirm-name"
                        placeholder={workspace.name}
                        value={confirmName}
                        onChange={(e) => setConfirmName(e.target.value)}
                        autoComplete="off"
                      />
                      <p className="text-muted-foreground text-xs">
                        The workspace and its memberships, roles, invites, keys, jobs, conversations and notifications will be
                        permanently removed. Audit entries are retained.
                      </p>
                    </div>
                    <DialogFooter>
                      <Button variant="outline" onClick={() => setDeleteOpen(false)} disabled={isDeleting}>
                        Cancel
                      </Button>
                      <Button
                        variant="destructive"
                        disabled={confirmName !== workspace.name || isDeleting}
                        onClick={() => {
                          deleteWorkspace(
                            {
                              resource: "workspaces",
                              id: workspace.id,
                              successNotification: false,
                              errorNotification: false,
                            },
                            {
                              onSuccess: () => {
                                toast.success(`Workspace “${workspace.name}” deleted`);
                                // Clear the stored workspace id if we just deleted the active one —
                                // WorkspaceProvider will auto-pick the next workspace after refresh,
                                // but clearing the stale id avoids a flash of “not a member”.
                                if (workspaceStore.get() === workspace.id) {
                                  workspaceStore.clear();
                                }
                                setDeleteOpen(false);
                                setConfirmName("");
                                refresh();
                                navigate("/", { replace: true });
                              },
                              onError: (err: unknown) => {
                                const msg =
                                  (err as { message?: string })?.message || "Failed to delete workspace";
                                toast.error(msg);
                              },
                            },
                          );
                        }}
                      >
                        {isDeleting ? "Deleting…" : "Delete workspace"}
                      </Button>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>
                {!canDelete?.can && (
                  <p className="text-muted-foreground text-xs">You need owner permission to delete this workspace.</p>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
