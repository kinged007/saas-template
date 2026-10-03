import { useMemo, useState } from "react";
import { useCan, useCustomMutation, useGetIdentity, useGo, useInvalidate } from "@refinedev/core";
import { useWorkspaceCustom } from "../hooks/useWorkspaceQuery";
import { useParams } from "react-router";
import { ArrowLeft, History, Pencil, Play } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  EmptyRow,
  JobRunStatusBadge,
  ReadError,
  formatDate,
  formatDuration,
} from "../components/ui";
import { errorMessage } from "../utils/errorMessage";
import type { Identity, JobParamSpec, JobRun, ScheduledJob } from "../types";

const MASK = "••••••••";

function ParamField({
  name,
  spec,
  value,
  onChange,
}: {
  name: string;
  spec: JobParamSpec;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const label = spec.label ?? name;
  if (spec.type === "password") {
    return (
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`param-${name}`}>{label}</Label>
        <Input
          id={`param-${name}`}
          type="password"
          autoComplete="new-password"
          placeholder={typeof value === "string" && value ? MASK : "not set"}
          onChange={(e) => onChange(e.target.value)}
        />
        <p className="text-muted-foreground text-xs">
          Leave blank to keep the stored value.
        </p>
      </div>
    );
  }
  if (spec.type === "int" || spec.type === "float") {
    return (
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`param-${name}`}>
          {label}
          {spec.min !== undefined && spec.max !== undefined
            ? ` (${spec.min}–${spec.max})`
            : ""}
        </Label>
        <Input
          id={`param-${name}`}
          type="number"
          step={spec.type === "int" ? 1 : "any"}
          value={typeof value === "number" ? String(value) : ""}
          onChange={(e) =>
            onChange(e.target.value === "" ? null : Number(e.target.value))
          }
        />
      </div>
    );
  }
  if (spec.type === "date") {
    return (
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`param-${name}`}>{label}</Label>
        <Input
          id={`param-${name}`}
          type="date"
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={`param-${name}`}>{label}</Label>
      <Input
        id={`param-${name}`}
        value={typeof value === "string" ? value : ""}
        maxLength={spec.max_length}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function EditDialog({
  job,
  url,
  open,
  onOpenChange,
}: {
  job: ScheduledJob;
  /** API url prefix for PATCH: "jobs/{id}" or "jobs/global/{id}". */
  url: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const invalidate = useInvalidate();
  const [cron, setCron] = useState(job.cron_schedule);
  const [enabled, setEnabled] = useState(job.enabled);
  const [policy, setPolicy] = useState(job.missed_policy);
  const [params, setParams] = useState<Record<string, unknown>>({
    ...job.params,
  });
  const { mutate: patch, mutation: patchMutation } = useCustomMutation();

  // Re-seed local state whenever the dialog is (re)opened for a job.
  const seededFor = useMemo(() => job.id + job.updated_at, [job.id, job.updated_at]);
  const [lastSeed, setLastSeed] = useState("");
  if (open && lastSeed !== seededFor) {
    setCron(job.cron_schedule);
    setEnabled(job.enabled);
    setPolicy(job.missed_policy);
    setParams({ ...job.params });
    setLastSeed(seededFor);
  }

  const paramEntries = Object.entries(job.params_schema ?? {});

  const submit = () => {
    const payload: Record<string, unknown> = {
      cron_schedule: cron,
      enabled,
      missed_policy: policy,
      params: Object.fromEntries(
        Object.entries(params).map(([key, value]) => [
          key,
          // blank password fields keep the stored secret
          job.params_schema?.[key]?.type === "password" && (value === "" || value == null)
            ? MASK
            : value,
        ]),
      ),
    };
    patch(
      {
        url,
        method: "patch",
        values: payload,
        successNotification: {
          message: "Job updated",
          type: "success",
        },
      },
      {
        onSuccess: () => {
          invalidate({ resource: "jobs", invalidates: ["list", "detail"] });
          onOpenChange(false);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit “{job.name}”</DialogTitle>
          <DialogDescription>{job.description}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="job-cron">Cron schedule</Label>
            <Input
              id="job-cron"
              className="font-mono"
              value={cron}
              onChange={(e) => setCron(e.target.value)}
            />
            <p className="text-muted-foreground text-xs">
              Five-field cron expression, e.g. <code>*/15 * * * *</code>.
              Evaluated in UTC.
            </p>
          </div>

          <div className="flex items-center justify-between rounded-md border p-3">
            <div>
              <Label htmlFor="job-enabled">Enabled</Label>
              <p className="text-muted-foreground text-xs">
                Disabled jobs keep their configuration but never fire.
              </p>
            </div>
            <Checkbox
              id="job-enabled"
              checked={enabled}
              onCheckedChange={(checked) => setEnabled(checked === true)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Missed schedules</Label>
            <Select
              value={policy}
              onValueChange={(v) =>
                setPolicy(v as ScheduledJob["missed_policy"])
              }
            >
              <SelectTrigger>
                <SelectValue>
                  {policy === "ignore" ? "Ignore missed runs" : "Catch up once (fire immediately)"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="single">
                  Catch up once (fire immediately)
                </SelectItem>
                <SelectItem value="ignore">Ignore missed runs</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">
              What to do with occurrences that came due while nothing could run.
            </p>
          </div>

          {paramEntries.length > 0 && (
            <div className="flex flex-col gap-3 rounded-md border p-3">
              <Label>Parameters</Label>
              {paramEntries.map(([name, spec]) => (
                <ParamField
                  key={name}
                  name={name}
                  spec={spec}
                  value={params[name]}
                  onChange={(value) =>
                    setParams((prev) => ({ ...prev, [name]: value }))
                  }
                />
              ))}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={patchMutation.isPending}>
            {patchMutation.isPending ? "Saving…" : "Save changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function JobDetailPage() {
  const go = useGo();
  const { data: identity } = useGetIdentity<Identity>();
  const isSuperuser = identity?.is_superuser === true;
  const routeParams = useParams();
  const jobId = routeParams.id ?? "";

  const { data: canEdit } = useCan({ resource: "jobs", action: "edit" });

  // Unified detail endpoint — backend decides access by job scope (global→superuser, workspace→jobs:read)
  const { result: jobResult, query: jobQuery } = useWorkspaceCustom<ScheduledJob>({
    url: `jobs/${jobId}`,
    method: "get",
  });
  // While pending/erroring, refine surfaces an empty object — treat as "not loaded yet".
  const job =
    jobResult?.data && Object.keys(jobResult.data).length > 0
      ? jobResult.data
      : undefined;
  const isLoading = jobQuery.isPending;
  const isGlobal = job?.scope === "global";
  // re-evaluate after job is known: global → superuser, workspace → jobs:update
  const canEditJob = isGlobal ? isSuperuser : canEdit?.can === true;

  const {
    result: runsResult,
    query: runsQuery,
  } = useWorkspaceCustom<JobRun[]>({
    url: `jobs/${jobId}/runs?limit=50&sort[]=scheduled_at&order[]=desc`,
    method: "get",
    queryOptions: { enabled: !!job },
  });
  // refine v5 falls back to an empty OBJECT (not undefined) while queries
  // are pending/erroring — normalize before mapping.
  const runs = Array.isArray(runsResult?.data) ? runsResult.data : [];
  const refetchRuns = runsQuery.refetch;

  const { mutate: execute } = useCustomMutation();
  const invalidate = useInvalidate();

  const [editOpen, setEditOpen] = useState(false);

  if (isLoading) {
    return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  }
  if (!job) {
    // refine raises no toast for a failed read — the body's copy is the
    // report, so it has to carry the reason, not just "nothing here".
    return (
      <p className="text-muted-foreground p-4 text-sm">
        {jobQuery.error ? errorMessage(jobQuery.error) : "Job not found."}
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
            onClick={() => go({ to: "/jobs" })}
          >
            <ArrowLeft className="h-4 w-4" />
            All jobs
          </Button>
          <h2 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            {job.name}
            {isGlobal && <Badge variant="secondary">global</Badge>}
          </h2>
          <p className="text-muted-foreground mt-1 max-w-2xl">
            {job.description}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {canEditJob && (
            <>
              <Button variant="outline" onClick={() => setEditOpen(true)}>
                <Pencil className="h-4 w-4" />
                Edit
              </Button>
              <Button
                onClick={() =>
                  execute(
                    {
                      url: `jobs/${job.id}/execute`,
                      method: "post",
                      values: {},
                      successNotification: {
                        message: "Execution queued",
                        description: `${job.name} will start shortly.`,
                        type: "success",
                      },
                    },
                    {
                      onSuccess: () =>
                        invalidate({
                          resource: "jobs",
                          invalidates: ["list", "detail"],
                        }),
                    },
                  )
                }
              >
                <Play className="h-4 w-4" />
                Execute now
              </Button>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border md:grid-cols-5">
        {[
          {
            label: "Schedule (cron, UTC)",
            value: <span className="font-mono">{job.cron_schedule}</span>,
          },
          {
            label: "Status",
            value: job.enabled ? (
              <Badge variant="success">enabled</Badge>
            ) : (
              <Badge variant="warning">disabled</Badge>
            ),
          },
          { label: "Next run", value: formatDate(job.next_run_at) },
          { label: "Last run", value: formatDate(job.last_run_at) },
          {
            label: "Timeout",
            value: formatDuration(job.timeout_seconds * 1000),
          },
        ].map(({ label, value }) => (
          <div
            key={label}
            className="flex flex-col gap-1 bg-background p-4"
          >
            <span className="text-muted-foreground text-xs uppercase tracking-wide">
              {label}
            </span>
            <span className="text-sm font-medium">{value}</span>
          </div>
        ))}
      </div>
      <p className="text-muted-foreground -mt-2 text-xs">
        Cron schedules are evaluated in UTC; run times are shown in your local
        timezone.
      </p>

      {Object.keys(job.params_schema ?? {}).length > 0 && (
        <div className="rounded-lg border p-4">
          <h3 className="mb-3 font-semibold">Configuration</h3>
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(job.params_schema).map(([name, spec]) => {
              const value = job.params?.[name];
              const display =
                spec.type === "password"
                  ? typeof value === "string" && value
                    ? MASK
                    : "not set"
                  : value == null || value === ""
                    ? "—"
                    : String(value);
              return (
                <div key={name}>
                  <dt className="text-muted-foreground text-xs">
                    {spec.label ?? name}
                    <span className="ml-1 opacity-60">({spec.type})</span>
                  </dt>
                  <dd className="truncate font-mono text-sm" title={display}>
                    {display}
                  </dd>
                  {spec.help && (
                    <dd className="text-muted-foreground text-xs">{spec.help}</dd>
                  )}
                </div>
              );
            })}
          </dl>
        </div>
      )}

      <div className="flex items-center gap-2">
        <History className="text-muted-foreground h-4 w-4" />
        <h3 className="font-semibold">Execution history</h3>
        <Button variant="ghost" size="sm" onClick={() => refetchRuns()}>
          Refresh
        </Button>
      </div>
      <ReadError error={runsQuery.error} className="p-0" />
      <div className="border-border overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Status</TableHead>
              <TableHead>Trigger</TableHead>
              <TableHead>Scheduled</TableHead>
              <TableHead>Started</TableHead>
              <TableHead>Duration</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs.map((run) => (
              <TableRow
                key={run.id}
                className="cursor-pointer"
                onClick={() => go({ to: `/jobs/${job.id}/runs/${run.id}` })}
              >
                <TableCell>
                  <JobRunStatusBadge status={run.status} />
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {run.trigger}
                </TableCell>
                <TableCell className="text-muted-foreground whitespace-nowrap">
                  {formatDate(run.scheduled_at)}
                </TableCell>
                <TableCell className="text-muted-foreground whitespace-nowrap">
                  {formatDate(run.started_at)}
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  {formatDuration(run.duration_ms)}
                </TableCell>
              </TableRow>
            ))}
            {runs.length === 0 && (
              <EmptyRow colSpan={5}>This job has not run yet.</EmptyRow>
            )}
          </TableBody>
        </Table>
      </div>

      {canEditJob && (
        <EditDialog
          job={job}
          url={`jobs/${job.id}`}
          open={editOpen}
          onOpenChange={setEditOpen}
        />
      )}
    </div>
  );
}
