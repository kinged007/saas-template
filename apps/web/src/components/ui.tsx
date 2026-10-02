import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";
import type { JobRunStatus } from "../types";
import { statusBadgeVariant, type StatusBadgeStatus } from "./status-badge";

export function StatusBadge({ status }: { status: StatusBadgeStatus }) {
  return <Badge variant={statusBadgeVariant(status)}>{status}</Badge>;
}

export function JobRunStatusBadge({ status }: { status: JobRunStatus }) {
  const variant =
    status === "success"
      ? "success"
      : status === "failed" || status === "timed_out"
        ? "destructive"
        : status === "running" || status === "pending"
          ? "warning"
          : "secondary";
  return <Badge variant={variant as "secondary"}>{status.replace("_", " ")}</Badge>;
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
        {subtitle && <p className="text-muted-foreground mt-1">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

export function EmptyRow({ colSpan, children }: { colSpan: number; children: ReactNode }) {
  return (
    <tr>
      <td colSpan={colSpan} className="text-muted-foreground h-24 text-center text-sm">
        {children}
      </td>
    </tr>
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
