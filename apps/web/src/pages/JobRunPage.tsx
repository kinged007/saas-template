import { useEffect } from "react";
import { useGo } from "@refinedev/core";
import { useWorkspaceCustom } from "../hooks/useWorkspaceQuery";
import { useParams } from "react-router";
import { ArrowLeft, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { JobRunStatusBadge, ReadError, formatDate, formatDuration } from "../components/ui";
import { errorMessage } from "../utils/errorMessage";
import type { JobLogEntry, JobRun, ScheduledJob } from "../types";

export function JobRunPage() {
  const go = useGo();
  const routeParams = useParams();
  const jobId = routeParams.id ?? "";
  const runId = routeParams.runId ?? "";

  const {
    result: runResult,
    query: runQuery,
  } = useWorkspaceCustom<JobRun>({
    url: `jobs/runs/${runId}`,
    method: "get",
  });
  // While pending/erroring, refine surfaces an empty object — treat as "not loaded yet".
  const run =
    runResult?.data && Object.keys(runResult.data).length > 0
      ? runResult.data
      : undefined;
  const isLoading = runQuery.isPending;
  const refetchRun = runQuery.refetch;

  const {
    result: logsResult,
    query: logsQuery,
  } = useWorkspaceCustom<JobLogEntry[]>({
    url: `jobs/runs/${runId}/logs`,
    method: "get",
    queryOptions: { enabled: !!run },
  });
  // refine v5 falls back to an empty OBJECT (not undefined) while queries are
  // pending/erroring — mapping it would throw. Normalize before rendering.
  const logs = Array.isArray(logsResult?.data) ? logsResult.data : [];
  const refetchLogs = logsQuery.refetch;
  const logsFetching = logsQuery.isFetching;

  // Poll while the run has not reached a terminal state.
  const isActive = run?.status === "pending" || run?.status === "running";
  useEffect(() => {
    if (!isActive) return;
    const timer = setInterval(() => {
      refetchRun();
      refetchLogs();
    }, 3000);
    return () => clearInterval(timer);
  }, [isActive, refetchRun, refetchLogs]);

  const { result: jobResult, query: jobQuery } = useWorkspaceCustom<ScheduledJob>({
    url: `jobs/${jobId}`,
    method: "get",
    queryOptions: { enabled: !!jobId },
  });
  const job =
    jobResult?.data && Object.keys(jobResult.data).length > 0
      ? jobResult.data
      : undefined;

  if (isLoading) {
    return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  }
  if (!run) {
    // The heading's job fetch carries no page state (the name falls back to
    // "job"), so this refusal is reported here, once, with the server's reason.
    return (
      <p role="alert" className="text-muted-foreground p-4 text-sm">
        {runQuery.error || jobQuery.error
          ? errorMessage(runQuery.error ?? jobQuery.error)
          : "Run not found."}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2 mb-1"
            onClick={() => go({ to: `/jobs/${jobId}` })}
          >
            <ArrowLeft className="h-4 w-4" />
            Back to job
          </Button>
          <h2 className="flex items-center gap-3 text-2xl font-bold tracking-tight">
            Run of {job?.name ?? "job"}
            <JobRunStatusBadge status={run.status} />
          </h2>
        </div>
        <Button variant="outline" onClick={() => refetchLogs()}>
          <RefreshCw className={logsFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
          Refresh
        </Button>
      </div>

      {run.error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-4">
          <h3 className="mb-1 font-semibold text-destructive">Error</h3>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap font-mono text-xs">
            {run.error}
          </pre>
        </div>
      )}

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border md:grid-cols-6">
        {[
          { label: "Trigger", value: run.trigger },
          { label: "Status", value: run.status.replace("_", " ") },
          { label: "Scheduled", value: formatDate(run.scheduled_at) },
          { label: "Started", value: formatDate(run.started_at) },
          { label: "Finished", value: formatDate(run.finished_at) },
          { label: "Duration", value: formatDuration(run.duration_ms) },
        ].map(({ label, value }) => (
          <div key={label} className="flex flex-col gap-1 bg-background p-4">
            <span className="text-muted-foreground text-xs uppercase tracking-wide">
              {label}
            </span>
            <span className="text-sm font-medium">{value}</span>
          </div>
        ))}
      </div>

      {Object.keys(run.params ?? {}).length > 0 && (
        <div className="rounded-lg border p-4">
          <h3 className="mb-1 font-semibold">Configuration used</h3>
          <p className="text-muted-foreground mb-3 text-xs">
            Snapshot taken when this run was queued. Secrets are masked.
          </p>
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(run.params ?? {}).map(([name, value]) => (
              <div key={name}>
                <dt className="text-muted-foreground text-xs">{name}</dt>
                <dd
                  className="truncate font-mono text-sm"
                  title={value == null ? "" : String(value)}
                >
                  {value == null || value === "" ? "—" : String(value)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      <div className="flex items-center gap-2">
        <h3 className="font-semibold">Audit log</h3>
        {isActive && (
          <Badge variant="outline" className="animate-pulse">
            live — refreshing every 3s
          </Badge>
        )}
      </div>
      <div className="overflow-hidden rounded-lg border">
        {logsQuery.error ? (
          <ReadError error={logsQuery.error} className="p-0" />
        ) : logs.length === 0 ? (
          <p className="text-muted-foreground p-4 text-sm">
            {isActive ? "Waiting for output…" : "No output was captured."}
          </p>
        ) : (
          <pre className="bg-muted/30 max-h-[480px] overflow-auto p-4 font-mono text-xs leading-relaxed">
            {logs.map((entry) => (
              <div key={entry.seq} className="flex gap-3">
                <span className="text-muted-foreground w-20 shrink-0 select-none">
                  {new Date(entry.ts).toLocaleTimeString()}
                </span>
                <span
                  className={`w-14 shrink-0 ${
                    entry.level === "ERROR"
                      ? "text-destructive"
                      : entry.level === "WARNING"
                        ? "text-yellow-600 dark:text-yellow-500"
                        : "text-muted-foreground"
                  }`}
                >
                  {entry.level}
                </span>
                <span className="whitespace-pre-wrap break-all">
                  {entry.message}
                </span>
              </div>
            ))}
          </pre>
        )}
      </div>
    </div>
  );
}
