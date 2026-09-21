import { useState } from "react";
import { toast } from "sonner";

import { useCan } from "@refinedev/core";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import { API_URL, httpClient } from "@/providers/dataProvider";

const CSV_RESOURCES = ["members", "invitations", "api_keys", "jobs", "conversations", "notifications"] as const;

function downloadBlob(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export function WorkspaceExportCard() {
  const { workspace } = useWorkspace();
  const { data: canExport } = useCan({ resource: "audit", action: "list" });
  const [resource, setResource] = useState<string>("members");
  const [busy, setBusy] = useState<"json" | "csv" | null>(null);

  const download = async (kind: "json" | "csv") => {
    setBusy(kind);
    try {
      const params = kind === "csv" ? { format: "csv", resource } : {};
      const resp = await httpClient.get(`${API_URL}/workspaces/export`, {
        params,
        responseType: "blob",
      });
      const disposition = String(resp.headers["content-disposition"] ?? "");
      const match = disposition.match(/filename="?([^"]+)"?/);
      const filename = match?.[1] ?? `workspace-export.${kind === "csv" ? "csv" : "json"}`;
      downloadBlob(resp.data as Blob, filename);
      toast.success("Export downloaded");
    } catch (e: unknown) {
      toast.error((e as { message?: string })?.message ?? "Export failed");
    } finally {
      setBusy(null);
    }
  };

  if (!workspace) return null;
  if (canExport && !canExport.can) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Data export</CardTitle>
        <CardDescription>
          Download a complete, importable-shaped dump of this workspace (members, roles, conversations, jobs,
          notifications, webhooks). Secrets (API key values, webhook signing secrets, job secret params) are never
          included — re-mint them after import.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" disabled={busy !== null} onClick={() => download("json")}>
            {busy === "json" ? "Exporting…" : "Export workspace (JSON)"}
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={resource} onValueChange={setResource}>
            <SelectTrigger className="w-48">
              <SelectValue placeholder="Resource" />
            </SelectTrigger>
            <SelectContent>
              {CSV_RESOURCES.map((r) => (
                <SelectItem key={r} value={r}>
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" disabled={busy !== null} onClick={() => download("csv")}>
            {busy === "csv" ? "Exporting…" : "Export CSV"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
