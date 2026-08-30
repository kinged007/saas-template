import { useState } from "react";
import { useCreate, useList } from "@refinedev/core";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage, FormDescription } from "@/components/ui/form";
import { TiptapEditor } from "./TiptapEditor";
import type { Member, Conversation } from "@/types";
import { getMemberDisplayName } from "@/types";
import { useWorkspace } from "@/contexts/WorkspaceContext";

const schema = z.object({
  title: z.string().max(300, "Title must be at most 300 characters").optional(),
  participantIds: z.array(z.string()).min(1, "Select at least one participant").max(19, "Max 19 other participants"),
  initialMessage: z.string().min(1, "Message is required").max(5000, "Message must be at most 5000 characters"),
});

type FormData = z.infer<typeof schema>;

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (conversation: Conversation) => void;
};

export function ComposeDialog({ open, onOpenChange, onCreated }: Props) {
  const { workspace } = useWorkspace();
  const { result } = useList<Member>({
    resource: "members",
    pagination: { pageSize: 100 },
    queryOptions: { enabled: open && !!workspace?.id },
  });
  const members = result?.data ?? [];

  // Filter out current user? The API will add self automatically, but show all for selection; we'll exclude self from checkbox list for clarity.
  // Need identity to know self id
  // Use member list includes self; we can allow selecting self but it will be deduped. Prefer excluding self.
  // We'll fetch identity via useOne? For now, include all and let backend dedupe.
  const { mutateAsync, mutation } = useCreate<Conversation>();
  const isPending = (mutation as unknown as { isPending?: boolean })?.isPending ?? false;

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { title: "", participantIds: [], initialMessage: "" },
  });

  const [editorKey, setEditorKey] = useState(0);

  const onSubmit = async (data: FormData) => {
    const payload = {
      title: data.title?.trim() || null,
      participant_user_ids: data.participantIds,
      initial_message: data.initialMessage,
    };
    try {
      const res = await mutateAsync({
        resource: "conversations",
        values: payload,
        successNotification: false,
        errorNotification: false,
      });
      const conv = res?.data as unknown as Conversation;
      toast.success("Conversation created");
      form.reset({ title: "", participantIds: [], initialMessage: "" });
      setEditorKey((k) => k + 1);
      onOpenChange(false);
      if (conv && onCreated) onCreated(conv);
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message || String(err);
      toast.error("Could not create conversation", { description: msg });
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => {
      if (!v) {
        form.reset({ title: "", participantIds: [], initialMessage: "" });
        setEditorKey(k=>k+1);
      }
      onOpenChange(v);
    }}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle>New conversation</DialogTitle>
          <DialogDescription>Start a conversation with workspace members. Markdown supported.</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4">
            <FormField
              control={form.control}
              name="title"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Title (optional)</FormLabel>
                  <FormControl>
                    <Input placeholder="Project discussion" {...field} />
                  </FormControl>
                  <FormDescription>Subject — like an email. Leave blank to auto-generate.</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="participantIds"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Participants</FormLabel>
                  <FormDescription>Select 1 to 19 other members (max 20 including you).</FormDescription>
                  <FormControl>
                    <div className="max-h-48 overflow-y-auto rounded border p-2">
                      {members.length === 0 ? (
                        <p className="text-muted-foreground text-sm">No members found.</p>
                      ) : (
                        members.map((m) => (
                          <label key={m.id} className="flex cursor-pointer items-center gap-2 py-1 text-sm">
                            <Checkbox
                              checked={field.value.includes(m.id)}
                              onCheckedChange={(checked) => {
                                const next = checked
                                  ? [...field.value, m.id]
                                  : field.value.filter((x) => x !== m.id);
                                field.onChange(next);
                              }}
                            />
                            <span className="flex-1 truncate">{getMemberDisplayName(m)} <span className="text-muted-foreground">({m.email})</span></span>
                            <span className="text-muted-foreground text-xs">{m.role}</span>
                          </label>
                        ))
                      )}
                    </div>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="initialMessage"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Message</FormLabel>
                  <FormControl>
                    <TiptapEditor
                      key={editorKey}
                      value={field.value}
                      onChange={(md) => field.onChange(md)}
                      placeholder="Write a message…"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
                Cancel
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending ? "Creating…" : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
