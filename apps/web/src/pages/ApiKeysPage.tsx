import { useCan } from "@refinedev/core";
import { useWorkspaceList } from "../hooks/useWorkspaceQuery";
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

/** Past its expiry the key already fails auth, before the job revokes it. */
function isExpired(key: ApiKey): boolean {
  return !!key.expires_at && new Date(key.expires_at).getTime() <= Date.now();
}

export function ApiKeysPage() {
  const { result } = useWorkspaceList<ApiKey>({ resource: "api-keys" });
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
              <TableHead>Expires</TableHead>
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
                  {key.usage_quota != null ? ` / ${key.usage_quota}` : ""}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDate(key.expires_at)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDate(key.last_used_at)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDate(key.created_at)}
                </TableCell>
                <TableCell className="text-right">
                  {key.revoked_at ? (
                    <Badge variant="secondary">
                      {isExpired(key) ? "expired" : "revoked"}
                    </Badge>
                  ) : isExpired(key) ? (
                    <Badge variant="secondary">expired</Badge>
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
              <EmptyRow colSpan={7}>No API keys yet.</EmptyRow>
            )}
          </TableBody>
        </Table>
      </div>
    </ListView>
  );
}