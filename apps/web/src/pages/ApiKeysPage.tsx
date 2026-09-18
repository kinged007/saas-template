import { useCan, useList } from "@refinedev/core";
import { KeyRound } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DeleteButton } from "../components/refine-ui/buttons/delete";
import {
  ListView,
  ListViewHeader,
} from "../components/refine-ui/views/list-view";
import { EmptyRow, formatDate } from "../components/ui";
import type { ApiKey } from "../types";

export function ApiKeysPage() {
  const { result } = useList<ApiKey>({ resource: "api-keys" });
  const { data: canManage } = useCan({ resource: "api-keys", action: "delete" });

  const rows = result?.data ?? [];

  return (
    <ListView>
      <ListViewHeader title="API Keys" />
      <div className="border-border overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Permissions</TableHead>
              <TableHead>Usage</TableHead>
              <TableHead>Last used</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((key) => (
              <TableRow key={key.id}>
                <TableCell>
                  <p className="flex items-center gap-2 font-medium">
                    <KeyRound className="text-muted-foreground h-4 w-4" />
                    {key.name}
                  </p>
                  <p className="text-muted-foreground text-xs font-mono">
                    {key.key_prefix}••••••••
                  </p>
                </TableCell>
                <TableCell>
                  <div className="flex max-w-64 flex-wrap gap-1">
                    {key.permissions.length === 0 ? (
                      <span className="text-muted-foreground text-xs">none</span>
                    ) : (
                      key.permissions.map((p) => (
                        <Badge key={p} variant="outline" className="text-xs">
                          {p}
                        </Badge>
                      ))
                    )}
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {key.usage_count ?? 0}
                  {key.monthly_quota != null ? ` / ${key.monthly_quota}` : ""}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDate(key.last_used_at)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDate(key.created_at)}
                </TableCell>
                <TableCell className="text-right">
                  {key.revoked_at ? (
                    <Badge variant="secondary">revoked</Badge>
                  ) : (
                    canManage?.can && (
                      <DeleteButton
                        resource="api-keys"
                        recordItemId={key.id}
                        variant="ghost"
                        size="sm"
                      />
                    )
                  )}
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <EmptyRow colSpan={6}>No API keys yet.</EmptyRow>
            )}
          </TableBody>
        </Table>
      </div>
    </ListView>
  );
}