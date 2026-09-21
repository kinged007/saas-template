import { useMemo, useState } from "react";
import { useCreate, useGetIdentity } from "@refinedev/core";
import { useWorkspaceList } from "../../hooks/useWorkspaceQuery";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { toast } from "sonner";
import { Check, ChevronsUpDown, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

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
import type { Identity, Member, Conversation } from "@/types";
import { getMemberDisplayName } from "@/types";
import { UserAvatar } from "@/components/ui/user-avatar";
import { useWorkspace, IDENTITY_QUERY_OPTIONS } from "@/contexts/WorkspaceContext";
import { cn } from "@/lib/utils";

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
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  const currentUserId = identity?.id ?? null;

  const { result } = useWorkspaceList<Member>({
    resource: "members",
    pagination: { pageSize: 100 },
    queryOptions: { enabled: open && !!workspace?.id },
  });
  const members = result?.data ?? [];

  const selectableMembers = useMemo(() => {
    if (!currentUserId) return members;
    return members.filter((m) => m.id !== currentUserId);
  }, [members, currentUserId]);

  const { mutateAsync, mutation } = useCreate<Conversation>();
  const isPending = (mutation as unknown as { isPending?: boolean })?.isPending ?? false;

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { title: "", participantIds: [], initialMessage: "" },
  });

  const [editorKey, setEditorKey] = useState(0);
  const [comboOpen, setComboOpen] = useState(false);

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
      setComboOpen(false);
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
        setComboOpen(false);
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

            {/* Flex container for participant selector + future select box */}
            <div className="flex gap-2">
              <FormField
                control={form.control}
                name="participantIds"
                render={({ field }) => {
                  const selectedIds = field.value as string[];
                  const toggle = (id: string) => {
                    const next = selectedIds.includes(id)
                      ? selectedIds.filter((x) => x !== id)
                      : [...selectedIds, id];
                    field.onChange(next);
                  };
                  const selectedMembers = selectableMembers.filter((m) => selectedIds.includes(m.id));

                  return (
                    <FormItem className="flex-1 min-w-0">
                      <FormLabel>Participants</FormLabel>
                      <FormDescription>Select 1 to 19 other members (max 20 including you).</FormDescription>
                      <Popover open={comboOpen} onOpenChange={setComboOpen}>
                        <PopoverTrigger asChild>
                          <FormControl>
                            <Button
                              variant="outline"
                              role="combobox"
                              aria-expanded={comboOpen}
                              className={cn(
                                "w-full justify-between h-auto min-h-9 px-3 py-2 font-normal",
                                selectedIds.length === 0 && "text-muted-foreground"
                              )}
                            >
                              <span className="flex flex-wrap gap-1 flex-1 text-left items-center min-w-0">
                                {selectedIds.length === 0 ? (
                                  "Select participants..."
                                ) : selectedMembers.length === 0 ? (
                                  `${selectedIds.length} selected`
                                ) : (
                                  <>
                                    {selectedMembers.slice(0, 3).map((m) => {
                                      const name = getMemberDisplayName(m);
                                      return (
                                        <span
                                          key={m.id}
                                          className="inline-flex items-center gap-1 rounded-md border bg-secondary px-1.5 py-0.5 text-xs font-medium"
                                          onClick={(e) => {
                                            e.preventDefault();
                                            e.stopPropagation();
                                            toggle(m.id);
                                          }}
                                        >
                                          <UserAvatar
                                            name={name}
                                            email={m.email}
                                            avatarUrl={m.avatar_url}
                                            sizeClassName="h-4 w-4"
                                            fallbackClassName="text-[8px]"
                                            firstName={m.first_name}
                                            lastName={m.last_name}
                                            withTooltip={false}
                                          />
                                          <span className="max-w-[80px] truncate">{name}</span>
                                          <X className="h-3 w-3 opacity-60 hover:opacity-100 shrink-0" />
                                        </span>
                                      );
                                    })}
                                    {selectedMembers.length > 3 && (
                                      <Badge variant="secondary" className="px-1.5 py-0.5 text-xs">
                                        +{selectedMembers.length - 3}
                                      </Badge>
                                    )}
                                    {selectedIds.length !== selectedMembers.length && selectedMembers.length <= 3 && (
                                      <span className="text-xs text-muted-foreground">
                                        +{selectedIds.length - selectedMembers.length} more
                                      </span>
                                    )}
                                  </>
                                )}
                              </span>
                              <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                            </Button>
                          </FormControl>
                        </PopoverTrigger>
                        <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
                          <Command>
                            <CommandInput placeholder="Search members..." className="h-9" />
                            <CommandList className="max-h-[200px] overflow-y-auto">
                              <CommandEmpty>No members found.</CommandEmpty>
                              <CommandGroup>
                                {selectableMembers.length === 0 ? (
                                  <div className="py-6 text-center text-sm text-muted-foreground">
                                    No other members found.
                                  </div>
                                ) : (
                                  selectableMembers.map((m) => {
                                    const name = getMemberDisplayName(m);
                                    const isSelected = selectedIds.includes(m.id);
                                    return (
                                      <CommandItem
                                        key={m.id}
                                        value={`${name} ${m.email} ${m.id}`}
                                        onSelect={() => toggle(m.id)}
                                        className="flex items-center gap-2 px-2 py-1.5"
                                      >
                                        <UserAvatar
                                          name={name}
                                          email={m.email}
                                          avatarUrl={m.avatar_url}
                                          sizeClassName="h-6 w-6"
                                          fallbackClassName="text-[10px]"
                                          firstName={m.first_name}
                                          lastName={m.last_name}
                                          withTooltip={false}
                                        />
                                        <span className="flex flex-1 min-w-0 flex-col text-left">
                                          <span className="truncate text-sm font-medium leading-none">{name}</span>
                                          <span className="truncate text-xs text-muted-foreground leading-none">{m.email}</span>
                                        </span>
                                        <span className="text-muted-foreground text-xs hidden sm:inline shrink-0">{m.role}</span>
                                        <Check
                                          className={cn(
                                            "ml-auto h-4 w-4 shrink-0",
                                            isSelected ? "opacity-100" : "opacity-0"
                                          )}
                                        />
                                      </CommandItem>
                                    );
                                  })
                                )}
                              </CommandGroup>
                            </CommandList>
                          </Command>
                        </PopoverContent>
                      </Popover>
                      <FormMessage />
                    </FormItem>
                  );
                }}
              />
            </div>

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
