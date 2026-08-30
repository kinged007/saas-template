import { useCan, useList } from "@refinedev/core";
import { Bot } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { DeleteButton } from "@/components/refine-ui/buttons/delete";
import { EditButton } from "@/components/refine-ui/buttons/edit";
import { ListView, ListViewHeader } from "@/components/refine-ui/views/list-view";
import { EmptyRow, formatDate } from "@/components/ui";
import type { Agent } from "@/types";

export function AgentsPage() {
  const { result } = useList<Agent>({ resource: "agents" });
  const { data: canEdit } = useCan({ resource: "agents", action: "edit" });
  const { data: canDelete } = useCan({ resource: "agents", action: "delete" });

  const rows = (result?.data ?? []) as Agent[];

  return (
    <ListView>
      <ListViewHeader title="Agents" />
      <div className="border-border overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Agent</TableHead>
              <TableHead>Slug</TableHead>
              <TableHead>Model</TableHead>
              <TableHead>Active</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((a) => (
              <TableRow key={a.id}>
                <TableCell>
                  <span className="flex items-center gap-2 font-medium">
                    <AgentAvatar value={a.avatar} name={a.name} sizeClassName="h-7 w-7" />
                    {a.name}
                  </span>
                </TableCell>
                <TableCell className="font-mono text-xs">{a.slug}</TableCell>
                <TableCell className="text-muted-foreground text-xs">
                  {a.model || <span className="italic">default</span>}
                </TableCell>
                <TableCell>
                  <Badge variant={a.is_active ? "success" : "secondary"}>
                    {a.is_active ? "active" : "inactive"}
                  </Badge>
                </TableCell>
                <TableCell className="text-muted-foreground text-xs">
                  {a.role_id ? a.role_id.slice(0, 8) + "…" : "—"}
                </TableCell>
                <TableCell className="text-muted-foreground">{formatDate(a.created_at)}</TableCell>
                <TableCell className="text-right">
                  <span className="inline-flex gap-1">
                    {canEdit?.can && (
                      <EditButton resource="agents" recordItemId={a.id} size="sm" variant="ghost" />
                    )}
                    {canDelete?.can && (
                      <DeleteButton resource="agents" recordItemId={a.id} size="sm" variant="ghost" />
                    )}
                  </span>
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <EmptyRow colSpan={7}>
                <span className="inline-flex items-center gap-2">
                  <Bot className="h-4 w-4" /> No agents yet.
                </span>
              </EmptyRow>
            )}
          </TableBody>
        </Table>
      </div>
    </ListView>
  );
}
