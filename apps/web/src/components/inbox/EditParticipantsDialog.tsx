import { useEffect, useMemo, useState } from "react";
import { useCustomMutation, useGetIdentity } from "@refinedev/core";
import { toast } from "sonner";
import { errorMessage } from "@/utils/errorMessage";
import { Check, ChevronsUpDown, X } from "lucide-react";

import { useWorkspace, IDENTITY_QUERY_OPTIONS } from "@/contexts/WorkspaceContext";
import { useWorkspaceList } from "../../hooks/useWorkspaceQuery";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { UserAvatar } from "@/components/ui/user-avatar";
import { cn } from "@/lib/utils";
import type { Identity, Member } from "../../types";
import { getMemberDisplayName } from "../../types";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  conversationId: string;
  /** Participant ids the conversation currently has. */
  participantIds: string[];
  onSaved: () => void;
};

export function EditParticipantsDialog({
  open,
  onOpenChange,
  conversationId,
  participantIds,
  onSaved,
}: Props) {
  const { workspace } = useWorkspace();
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  const currentUserId = identity?.id ?? null;

  // The wider member list is only fetched while the dialog is open.
  const { result } = useWorkspaceList<Member>({
    resource: "members",
    pagination: { pageSize: 100 },
    queryOptions: { enabled: open && !!workspace?.id },
  });
  const members = result?.data ?? [];

  const [selected, setSelected] = useState<string[]>(participantIds);
  const [comboOpen, setComboOpen] = useState(false);

  useEffect(() => {
    if (open) setSelected(participantIds);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const { mutateAsync, mutation } = useCustomMutation();
  const isPending = (mutation as unknown as { isPending?: boolean })?.isPending ?? false;

  // Members already in the conversation first, the rest of the workspace below.
  const { current, others } = useMemo(() => {
    const inConv = new Set(participantIds);
    return {
      current: members.filter((m) => inConv.has(m.id)),
      others: members.filter((m) => !inConv.has(m.id)),
    };
  }, [members, participantIds]);

  const selectedMembers = members.filter((m) => selected.includes(m.id));
  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const save = async () => {
    try {
      await mutateAsync({
        url: `conversations/${conversationId}/participants`,
        method: "patch",
        values: { participant_user_ids: selected },
        successNotification: false,
        errorNotification: false,
      });
      toast.success("Recipients updated");
      onSaved();
      onOpenChange(false);
    } catch (err: unknown) {
      toast.error("Could not update recipients", {
        description: errorMessage(err),
      });
    }
  };

  const renderMember = (m: Member) => {
    const name = getMemberDisplayName(m);
    const isSelected = selected.includes(m.id);
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
        <span className="flex min-w-0 flex-1 flex-col text-left">
          <span className="truncate text-sm font-medium leading-none">{name}</span>
          <span className="text-muted-foreground truncate text-xs leading-none">{m.email}</span>
        </span>
        {m.id !== currentUserId && (
          <span className="text-muted-foreground hidden shrink-0 text-xs sm:inline">{m.role}</span>
        )}
        <Check className={cn("ml-auto h-4 w-4 shrink-0", isSelected ? "opacity-100" : "opacity-0")} />
      </CommandItem>
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) setComboOpen(false);
        onOpenChange(v);
      }}
    >
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>Edit recipients</DialogTitle>
          <DialogDescription>
            People already in this conversation, then the rest of the workspace.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <p className="text-muted-foreground text-xs font-medium uppercase">
              In this conversation ({selected.length})
            </p>
            <div className="flex max-h-48 flex-col gap-1.5 overflow-y-auto">
              {selectedMembers.length === 0 ? (
                <p className="text-muted-foreground text-sm">Nobody selected yet.</p>
              ) : (
                selectedMembers.map((m) => {
                  const name = getMemberDisplayName(m);
                  const self = m.id === currentUserId;
                  return (
                    <div key={m.id} className="flex items-center gap-2 rounded-md border px-2 py-1.5">
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
                      <span className="flex min-w-0 flex-1 flex-col text-left">
                        <span className="truncate text-sm font-medium leading-none">
                          {name}
                          {self && <span className="text-muted-foreground font-normal"> (you)</span>}
                        </span>
                        {m.email && (
                          <span className="text-muted-foreground truncate text-xs leading-none">{m.email}</span>
                        )}
                      </span>
                      {self ? (
                        <Badge variant="secondary" className="shrink-0 text-[10px]">
                          required
                        </Badge>
                      ) : (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 shrink-0"
                          onClick={() => toggle(m.id)}
                          aria-label={`Remove ${name}`}
                          title={`Remove ${name}`}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          <Popover open={comboOpen} onOpenChange={setComboOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                role="combobox"
                aria-expanded={comboOpen}
                className="w-full justify-between font-normal"
              >
                <span className="min-w-0 truncate text-left">
                  Add people
                  {others.length > 0 && (
                    <span className="text-muted-foreground"> · {others.length} not in this conversation</span>
                  )}
                </span>
                <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
              <Command>
                <CommandInput placeholder="Search members..." className="h-9" />
                <CommandList className="max-h-[240px] overflow-y-auto">
                  <CommandEmpty>No members found.</CommandEmpty>
                  {current.length > 0 && (
                    <CommandGroup heading="In this conversation">{current.map(renderMember)}</CommandGroup>
                  )}
                  {others.length > 0 && (
                    <CommandGroup heading="Workspace members">{others.map(renderMember)}</CommandGroup>
                  )}
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <Button type="button" onClick={save} disabled={isPending || selectedMembers.length === 0}>
            {isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
