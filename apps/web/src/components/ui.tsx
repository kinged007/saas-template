import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";
import type { JobRunStatus } from "../types";
import { errorMessage } from "../utils/errorMessage";
import {
  jobRunBadgeVariant,
  statusBadgeVariant,
  type StatusBadgeStatus,
} from "./status-badge";

export function StatusBadge({ status }: { status: StatusBadgeStatus }) {
  return <Badge variant={statusBadgeVariant(status)}>{status}</Badge>;
}

export function JobRunStatusBadge({ status }: { status: JobRunStatus }) {
  return (
    <Badge variant={jobRunBadgeVariant(status)}>{status.replace("_", " ")}</Badge>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  className,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4", className)}>
      <div>
        <h2 className="text-2xl font-bold tracking-tight">{title}</h2>
        {/* Deliberate && (see #731): a JSX child drops "", unlike the inspected RoleCapNotice return fixed in #711. */}
        {subtitle && <p className="text-muted-foreground mt-1">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

export function EmptyRow({ colSpan, children }: { colSpan: number; children: ReactNode }) {
  // The role sits on the cell, not the row: a `status` row would lose its row
  // semantics (and the `getByRole("row")` assertions). `status` carries an
  // implicit polite live region, so the Loading → failure/empty swap is
  // announced — the same idiom as the inbox stale-messages note.
  return (
    <tr>
      <td
        colSpan={colSpan}
        role="status"
        className="text-muted-foreground h-24 text-center text-sm"
      >
        {children}
      </td>
    </tr>
  );
}

/**
 * In-body report for a failed read. refine raises no toast for reads (see
 * refine-ui/notification/read-failure.ts), so this is where the server's reason
 * reaches the user, and role="alert" announces it — a toast does not.
 */
export function ReadError({ error, className }: { error: unknown; className?: string }) {
  if (!error) return null;
  return (
    <p role="alert" className={cn("text-muted-foreground p-4 text-sm", className)}>
      {errorMessage(error)}
    </p>
  );
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

export function formatDuration(ms?: number | null): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}
