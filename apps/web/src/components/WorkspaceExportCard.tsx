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
    // The card reports this failure inline; refine's generic toast would
    // report the same failure a second time.
    errorNotification: false,
  });
  // refine's isLoading is `isFetching && !data`, which is true again while a
  // retry runs: the refetch targets a query that never resolved. A non-zero
  // errorUpdatedAt means an earlier attempt already failed, and that is what
  // tells a first load from a retry. Holding the card and its alert up while
  // the retry is in flight is the point: Retry shows as disabled, not gone.
  const retrying =
    resourcesQuery.isFetching && !resourcesQuery.data && resourcesQuery.errorUpdatedAt > 0;
  const resourcesFailed = resourcesQuery.isError || retrying;
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

  if (!workspace || isLoading || (resourcesQuery.isLoading && !resourcesQuery.errorUpdatedAt)) return null;
  if (canExport && !canExport.can) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Data export</CardTitle>
        <CardDescription>
          Download a read-only snapshot of this workspace: the workspace itself, members and their profiles,
          roles, invitations, conversations and their messages, jobs, API key metadata, webhook subscriptions,
          notifications, and the audit log. The JSON download is the full record. There is no import in this
          app — the file is for your own backup, or for loading into another system. The CSV download is a
          spreadsheet view of one selected resource, and cells a spreadsheet would read as a formula are prefixed
          with an apostrophe, so use the JSON for anything you intend to parse. Secrets (API key values, webhook
          signing secrets, secret job parameters) are never included — re-mint them yourself.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {resourcesFailed && (
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <p role="alert" className="text-sm text-destructive">
              Could not load the exportable resources. CSV export is unavailable; the JSON export below still
              works.
            </p>
            {/* Recovery is user-initiated: retry stays off so a mount makes one attempt, not a storm. */}
            <Button
              size="sm"
              variant="outline"
              disabled={resourcesQuery.isFetching}
              onClick={() => void resourcesQuery.refetch()}
            >
              Retry
            </Button>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Select value={resource} onValueChange={setResource} disabled={resourcesFailed}>
            <SelectTrigger className="w-48">
              <SelectValue placeholder="Resource">{resource}</SelectValue>
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
