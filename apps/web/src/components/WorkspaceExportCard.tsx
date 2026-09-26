import { useState } from "react";
import { toast } from "sonner";

import { useCan, useCustom } from "@refinedev/core";

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
  const { data: canExport, isLoading } = useCan({ resource: "audit", action: "list" });
  const { result: resourcesResult, query: resourcesQuery } = useCustom<{ resources: string[] }>({
    url: "workspaces/export/resources",
    method: "get",
    queryOptions: { enabled: !!workspace && canExport?.can === true, retry: false },
  });
  const resourcesFailed = resourcesQuery.isError;
  const resources = resourcesResult?.data?.resources ?? [];
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

  if (!workspace || isLoading || resourcesQuery.isLoading) return null;
  if (canExport && !canExport.can) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Data export</CardTitle>
        <CardDescription>
          Download a complete, importable-shaped dump of this workspace (members, roles, conversations, jobs,
          notifications, webhooks, audit log). Secrets (API key values, webhook signing secrets, job secret
          params) are never included — re-mint them after import.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {resourcesFailed && (
          <p className="mb-2 text-sm text-destructive">
            Could not load the exportable resources. CSV export is unavailable; the JSON export below still
            works.
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Select value={resource} onValueChange={setResource} disabled={resourcesFailed}>
            <SelectTrigger className="w-48">
              <SelectValue placeholder="Resource" />
            </SelectTrigger>
            <SelectContent>
              {resources.map((r) => (
                <SelectItem key={r} value={r}>
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            disabled={resourcesFailed || busy !== null}
            onClick={() => download("csv")}
          >
            {busy === "csv" ? "Exporting…" : "Export CSV"}
          </Button>
          <Button variant="outline" disabled={busy !== null} onClick={() => download("json")}>
            {busy === "json" ? "Exporting…" : "Export workspace (JSON)"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
