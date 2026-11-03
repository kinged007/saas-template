import { useEffect, useRef, useState } from "react";
import { useCan, useInvalidate } from "@refinedev/core";
import { useWorkspaceList } from "../hooks/useWorkspaceQuery";
import { KeyRound, Pencil, RotateCw } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/CopyButton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { API_URL, httpClient } from "../providers/dataProvider";
import { errorMessage } from "@/utils/errorMessage";
import type { ApiKey, ApiKeyRotated } from "../types";

/** Past its expiry the key already fails auth, before the job revokes it. */
function isExpired(key: ApiKey): boolean {
  return !!key.expires_at && new Date(key.expires_at).getTime() <= Date.now();
}

/** ISO instant → datetime-local value in the browser's timezone. */
function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function ApiKeysPage() {
  const { result } = useWorkspaceList<ApiKey>({ resource: "api-keys" });
  const { data: canManage } = useCan({ resource: "api-keys", action: "delete" });
  const invalidate = useInvalidate();

  const [rotatingId, setRotatingId] = useState<string | null>(null);
  // The raw secret is only returned once, so it lives here until the dialog
  // closes — then it is dropped and can never be rendered again.
  const [rotated, setRotated] = useState<ApiKeyRotated | null>(null);
  const [copied, setCopied] = useState(false);
  // Edit dialog state, seeded from the row it opens on. `null` expiry means
  // never expires; quota `null` means unlimited. Permissions are fixed at
  // mint — changing them means minting a new key.
  const [editing, setEditing] = useState<ApiKey | null>(null);
  const [editName, setEditName] = useState("");
  const [editQuota, setEditQuota] = useState("");
  const [editExpires, setEditExpires] = useState("");
  const [editNeverExpires, setEditNeverExpires] = useState(true);
  const [saving, setSaving] = useState(false);
  // One timer owns the 1.5 s confirmation: a second click restarts it instead
  // of stacking one that ends it early, and it dies with the component.
  const copyTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(copyTimer.current), []);

  const rows = result?.data ?? [];

  const closeRotatedDialog = () => {
    // The dialog goes away with the key it copies, so the confirmation must
    // not outlive it and greet the next rotated key.
    window.clearTimeout(copyTimer.current);
    setCopied(false);
    setRotated(null);
  };

  const copyRotatedKey = async () => {
    if (!rotated) return;
    // Clear before the write so the previous window dies even if this one never
    // reaches the clipboard.
    window.clearTimeout(copyTimer.current);
    try {
      await navigator.clipboard.writeText(rotated.key);
      setCopied(true);
      copyTimer.current = window.setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      // A denied write must not leave a stale confirmation: the timer above
      // was already cleared, so nothing would reset `copied`.
      setCopied(false);
      toast.error("Could not copy API key", {
        description: errorMessage(err),
      });
    }
  };
  const rotate = async (key: ApiKey) => {
    setRotatingId(key.id);
    try {
      const { data } = await httpClient.post(`${API_URL}/api-keys/${key.id}/rotate`, {});
      setRotated(data as ApiKeyRotated);
      invalidate({ resource: "api-keys", invalidates: ["list"] });
    } catch (err) {
      toast.error("Could not rotate API key", {
        description: errorMessage(err),
      });
    } finally {
      setRotatingId(null);
    }
  };

  const openEdit = (key: ApiKey) => {
    setEditing(key);
    setEditName(key.name);
    setEditQuota(key.usage_quota != null ? String(key.usage_quota) : "");
    setEditExpires(toLocalInput(key.expires_at));
    setEditNeverExpires(!key.expires_at);
  };

  const saveEdit = async () => {
    if (!editing) return;
    const name = editName.trim();
    if (!name) {
      toast.error("Name is required");
      return;
    }
    setSaving(true);
    try {
      // Every editable field is sent explicitly, so a cleared quota or
      // expiry reads as a clear, not as "left alone".
      const quota = editQuota.trim() === "" ? null : Number(editQuota);
      if (quota !== null && (!Number.isInteger(quota) || quota < 1)) {
        toast.error("Quota must be a whole number of at least 1, or empty for unlimited");
        return;
      }
      await httpClient.patch(`${API_URL}/api-keys/${editing.id}`, {
        name,
        usage_quota: quota,
        expires_at: editNeverExpires || editExpires.trim() === "" ? null : new Date(editExpires).toISOString(),
      });
      toast.success("API key updated");
      setEditing(null);
      invalidate({ resource: "api-keys", invalidates: ["list"] });
    } catch (err) {
      toast.error("Could not update API key", {
        description: errorMessage(err),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <ListView>
      <ListViewHeader title="API Keys" />
      <div className="border-border overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Permissions</TableHead>
              <TableHead>Usage (this month)</TableHead>
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
                  {key.usage_window_count ?? 0}
                  {key.usage_quota != null ? ` / ${key.usage_quota}` : ""}
                  <p className="text-xs">
                    <span className="sr-only">lifetime </span>
                    {key.usage_count ?? 0} total
                  </p>
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
                  {/* An expired key stays deletable: revocation is idempotent,
                      so the row never loses its only affordance while the
                      cleanup job has yet to run. */}
                  {key.revoked_at ? (
                    <Badge variant="secondary">
                      {isExpired(key) ? "expired" : "revoked"}
                    </Badge>
                  ) : (
                    <div className="flex items-center justify-end gap-2">
                      {isExpired(key) && (
                        <Badge variant="secondary">expired</Badge>
                      )}
                      {canManage?.can && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          title="Edit key"
                          disabled={rotatingId === key.id}
                          onClick={() => openEdit(key)}
                        >
                          <Pencil className="h-4 w-4" />
                          <span className="sr-only">Edit {key.name}</span>
                        </Button>
                      )}
                      {canManage?.can && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          title="Rotate secret"
                          disabled={rotatingId === key.id}
                          onClick={() => void rotate(key)}
                        >
                          <RotateCw className="h-4 w-4" />
                          <span className="sr-only">Rotate {key.name}</span>
                        </Button>
                      )}
                      {canManage?.can && (
                        <DeleteButton
                          resource="api-keys"
                          recordItemId={key.id}
                          variant="ghost"
                          size="sm"
                        />
                      )}
                    </div>
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

      <Dialog open={rotated !== null} onOpenChange={(open) => { if (!open) closeRotatedDialog(); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>API key rotated</DialogTitle>
            <DialogDescription>
              Copy the new secret now — for security it won't be shown again.
              The previous secret keeps working until {formatDate(rotated?.grace_expires_at)},
              then stops.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="rotated-key">New secret</Label>
            <div className="flex gap-2">
              <Input
                id="rotated-key"
                readOnly
                value={rotated?.key ?? ""}
                className="font-mono"
              />
              <CopyButton
                type="button"
                copied={copied}
                label="Copy rotated API key"
                onClick={() => void copyRotatedKey()}
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" onClick={closeRotatedDialog}>
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={editing !== null} onOpenChange={(open) => { if (!open) setEditing(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Edit API key</DialogTitle>
            <DialogDescription>
              Rename the key, change its monthly quota, or move its expiry.
              Permissions are fixed at mint — mint a new key to change them.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="edit-key-name">Name</Label>
              <Input
                id="edit-key-name"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                maxLength={150}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="edit-key-quota">Monthly usage quota</Label>
              <Input
                id="edit-key-quota"
                type="number"
                min={1}
                placeholder="Unlimited"
                value={editQuota}
                onChange={(e) => setEditQuota(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="edit-key-expires">Expires at</Label>
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 accent-primary"
                  checked={editNeverExpires}
                  onChange={(e) => setEditNeverExpires(e.target.checked)}
                />
                Never expires
              </label>
              {!editNeverExpires && (
                <Input
                  id="edit-key-expires"
                  type="datetime-local"
                  value={editExpires}
                  onChange={(e) => setEditExpires(e.target.value)}
                />
              )}
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={saving} onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button type="button" disabled={saving || !editName.trim()} onClick={() => void saveEdit()}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ListView>
  );
}
