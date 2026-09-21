import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { toast } from "sonner";
import { useCan, useCustomMutation, useDelete } from "@refinedev/core";
import { useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
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
import { workspaceStore } from "@/utils/storage";

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
  const { mutate: deleteWorkspace, mutation: deleteMutation } = useDelete();
  const isDeleting = deleteMutation.isPending;
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");

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

      <Separator />

      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 flex flex-col gap-3">
        <div>
          <h4 className="font-semibold text-destructive">Danger zone</h4>
          <p className="text-muted-foreground mt-1 text-sm">
            Deleting a workspace is <span className="font-semibold">permanent and irreversible</span>. The workspace
            and all its scoped data will be removed: members, roles, invitations, API keys, scheduled jobs and run
            history, conversations and messages, notifications, and stored secrets. User accounts themselves are
            global and are not deleted — members simply lose access to this workspace. Audit log entries are retained
            for compliance.
          </p>
          <p className="text-muted-foreground mt-2 text-sm">
            This action is gated on <code>workspace:delete</code> (owners only). Admins, editors and viewers cannot
            delete workspaces.
          </p>
        </div>

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
                <code>{workspace.slug}</code>) and all workspace-scoped data listed above. Users who were members
                will remain in the system but will no longer have access to this workspace. This cannot be undone.
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
  );
}
