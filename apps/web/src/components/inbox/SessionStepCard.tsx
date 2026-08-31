import { AlertTriangle, Brain, ChevronDown, Sparkles, Wrench } from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { formatDate } from "../ui";

/** One agent-run part from SessionStore: thinking, a tool call + its outcome. */
export interface SessionStep {
  message_id?: string;
  kind?: string;
  title?: string;
  content?: string;
  status?: string;
  created_at?: string;
}

interface KindMeta {
  icon: typeof Brain;
  label: string;
  panel: string;
  iconCls: string;
}

const KIND_META: Record<string, KindMeta> = {
  thinking: {
    icon: Brain,
    label: "Thinking",
    panel: "border-violet-200 bg-violet-50/60 dark:border-violet-800 dark:bg-violet-950/20",
    iconCls: "text-violet-500 dark:text-violet-400",
  },
  tool_call: {
    icon: Wrench,
    label: "Tool call",
    panel: "border-amber-200 bg-amber-50/60 dark:border-amber-800 dark:bg-amber-950/20",
    iconCls: "text-amber-500 dark:text-amber-400",
  },
  error: {
    icon: AlertTriangle,
    label: "Error",
    panel: "border-red-200 bg-red-50/60 dark:border-red-800 dark:bg-red-950/20",
    iconCls: "text-red-500 dark:text-red-400",
  },
};

export function SessionStepCard({ step }: { step: SessionStep }) {
  const meta = KIND_META[step.kind ?? ""] ?? {
    icon: Sparkles,
    label: step.title || step.kind || "Step",
    panel: "border-border bg-muted/30",
    iconCls: "text-muted-foreground",
  } satisfies KindMeta;
  const Icon = meta.icon;
  const failed = !!step.status && ["failed", "error"].includes(step.status.toLowerCase());

  return (
    <Collapsible className={cn("w-full max-w-[75%] rounded-lg border", meta.panel)}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-left">
        <Icon className={cn("h-3.5 w-3.5 shrink-0", meta.iconCls)} />
        <span className="truncate text-xs font-medium">
          {meta.label}
          {step.title && step.title !== meta.label ? `: ${step.title}` : ""}
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-2">
          {step.status && (
            <span className={cn("text-[10px] uppercase tracking-wide", failed ? "text-red-500" : "text-muted-foreground")}>
              {step.status}
            </span>
          )}
          <ChevronDown className="h-3.5 w-3.5 transition-transform data-[state=open]:rotate-180" />
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="px-3 pb-3">
        {step.content ? (
          <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-words rounded bg-background/70 p-2 font-mono text-[11px] leading-relaxed text-muted-foreground">
            {step.content}
          </pre>
        ) : null}
        {step.created_at ? <p className="mt-1.5 text-[10px] text-muted-foreground/70">{formatDate(step.created_at)}</p> : null}
      </CollapsibleContent>
    </Collapsible>
  );
}