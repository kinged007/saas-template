import { useCan, useCustom, useCustomMutation, useGetIdentity, useGo, useList } from "@refinedev/core";
import { Clock, Play, Settings2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyRow, formatDate } from "@/components/ui";
import type { Identity, ScheduledJob } from "@/types";

function JobTable({
  jobs,
  urlPrefix,
  canExecute,
  emptyText,
}: {
  jobs: ScheduledJob[];
  urlPrefix: string;
  canExecute: boolean;
  emptyText: string;
}) {
  const go = useGo();
  const { mutate: execute, mutation } = useCustomMutation();

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Job</TableHead>
          <TableHead>Schedule</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Next run</TableHead>
          <TableHead>Last run</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.map((job) => (
          <TableRow key={job.id}>
            <TableCell>
              <button className="max-w-md text-left" onClick={() => go({ to: `/jobs/${job.id}` })}>
                <p className="flex items-center gap-2 font-medium hover:underline">
                  <Clock className="text-muted-foreground h-4 w-4 shrink-0" />
                  {job.name}
                </p>
                <p className="text-muted-foreground truncate text-xs">{job.description}</p>
              </button>
            </TableCell>
            <TableCell className="font-mono text-xs">{job.cron_schedule}</TableCell>
            <TableCell>
              {job.enabled ? <Badge variant="success">enabled</Badge> : <Badge variant="warning">disabled</Badge>}
            </TableCell>
            <TableCell className="text-muted-foreground whitespace-nowrap">{formatDate(job.next_run_at)}</TableCell>
            <TableCell className="text-muted-foreground whitespace-nowrap">{formatDate(job.last_run_at)}</TableCell>
            <TableCell className="text-right">
              <div className="flex items-center justify-end gap-1">
                {canExecute && (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={mutation.isPending}
                    onClick={() =>
                      execute({
                        url: `jobs/${urlPrefix}${job.id}/execute`,
                        method: "post",
                        values: {},
                        successNotification: {
                          message: "Execution queued",
                          description: `${job.name} will start shortly.`,
                          type: "success",
                        },
                      })
                    }
                  >
                    <Play className="h-4 w-4" />
                    Execute now
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => go({ to: `/jobs/${job.id}` })}>
                  <Settings2 className="h-4 w-4" />
                  Configure
                </Button>
              </div>
            </TableCell>
          </TableRow>
        ))}
        {jobs.length === 0 && <EmptyRow colSpan={6}>{emptyText}</EmptyRow>}
      </TableBody>
    </Table>
  );
}

export function JobsSection() {
  const { data: identity } = useGetIdentity<Identity>();
  const isSuperuser = !!identity?.is_superuser;
  const { data: canEdit } = useCan({ resource: "jobs", action: "edit" });
  const canEditWorkspaceJobs = canEdit?.can ?? false;

  const { result: workspaceJobs } = useList<ScheduledJob>({ resource: "jobs" });
  const { result: globalResult } = useCustom<ScheduledJob[]>({
    url: "jobs/global",
    method: "get",
    queryOptions: { enabled: isSuperuser },
  });
  const workspaceList = Array.isArray(workspaceJobs?.data) ? workspaceJobs.data : [];
  const globalList = Array.isArray(globalResult?.data) ? globalResult.data : [];

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Scheduled Jobs</CardTitle>
          <CardDescription>
            Recurring jobs configured for this workspace. Open a job to edit its schedule and parameters, or inspect
            execution history. Cron schedules are evaluated in UTC.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <JobTable
              jobs={workspaceList}
              urlPrefix=""
              canExecute={canEditWorkspaceJobs}
              emptyText="No scheduled jobs in this workspace."
            />
          </div>
        </CardContent>
      </Card>

      {isSuperuser && (
        <Card>
          <CardHeader>
            <CardTitle>Global jobs</CardTitle>
            <CardDescription>Deployment-wide jobs — only superadmins can view and modify these.</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <JobTable jobs={globalList} urlPrefix="global/" canExecute emptyText="No global jobs." />
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
