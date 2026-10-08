import { Fragment, useState } from "react";
import { useCan } from "@refinedev/core";
import { useWorkspaceList } from "../hooks/useWorkspaceQuery";
import { cn } from "@/lib/utils";
import { Webhook } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CreateButton } from "../components/refine-ui/buttons/create";
import { DeleteButton } from "../components/refine-ui/buttons/delete";
import {
  ListView,
  ListViewHeader,
} from "../components/refine-ui/views/list-view";
import { EmptyRow, formatDate } from "../components/ui";
import type { WebhookDelivery, WebhookSubscription } from "../types";
import { useWebhookDeliveries, useWebhookRedeliver } from "./webhooks-hooks";

function DeliveryLog({ subscriptionId }: { subscriptionId: string }) {
  const { result, query } = useWebhookDeliveries(subscriptionId);
  // The delivery log is a `useCustom` query, so the redeliver has to refetch
  // it directly — invalidating the `webhooks` list key leaves it untouched.
  const { mutate: redeliver, mutation } = useWebhookRedeliver(() => {
    void query.refetch();
  });
  /* refine hands back a frozen empty object as `result.data` whenever the
     query has no data — a disabled query reports neither loading nor error —
     so the shape is checked once, before anything reaches `rows.map`. */
  const isList = Array.isArray(result?.data);
  const rows = isList ? result.data : [];

  if (query.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading deliveries…</p>;
  }
  /* A failed refetch keeps the rows react-query already had, and stale rows
     beat an error message; only a load that produced no data at all is one.
     Uncaptioned rows would read as current — the `staleNote` `<p>` below
     marks them instead. */
  if (query.isError && !isList) {
    return (
      <p className="text-destructive flex flex-wrap items-center gap-2 text-sm">
        Could not load deliveries: {query.error?.message ?? "Unknown error"}
        <Button variant="outline" size="sm" onClick={() => query.refetch()}>
          Try again
        </Button>
      </p>
    );
  }
  // A failed refetch leaves a cached empty list in place too — the pane must
  // caption it, not let "No deliveries yet." read as current.
  const staleNote = query.isError && isList;
  if (rows.length === 0) {
    return (
      <div>
        {/* Caption for a failed background refetch. Always mounted: a live
            region has to be in the accessibility tree before its text changes
            to be announced — `sr-only` keeps the idle (textless) state out of
            the layout. */}
        <p
          role="status"
          className={cn(
            "text-muted-foreground mb-2 text-sm",
            !staleNote && "sr-only",
          )}
        >
          {staleNote ? "Showing the last deliveries loaded." : ""}
        </p>
        <p className="text-muted-foreground text-sm">No deliveries yet.</p>
      </div>
    );
  }
  return (
    <div>
      {/* Caption for a failed background refetch, per InboxPage's staleness
          note. Always mounted: a live region has to be in the accessibility
          tree before its text changes to be announced — `sr-only` keeps the
          idle (textless) state out of the layout. */}
      <p
        role="status"
        className={cn(
          "text-muted-foreground mb-2 text-sm",
          !staleNote && "sr-only",
        )}
      >
        {staleNote ? "Showing the last deliveries loaded." : ""}
      </p>
      <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Event</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Attempts</TableHead>
          <TableHead>Response</TableHead>
          <TableHead>Error</TableHead>
          <TableHead>Created</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((d: WebhookDelivery) => (
          <TableRow key={d.id}>
            <TableCell className="font-mono text-xs">{d.event_type}</TableCell>
            <TableCell>
              <Badge
                variant={
                  d.status === "success"
                    ? "success"
                    : d.status === "exhausted"
                      ? "destructive"
                      : "warning"
                }
              >
                {d.status}
              </Badge>
            </TableCell>
            <TableCell>{d.attempt_count}</TableCell>
            <TableCell>{d.response_status ?? "—"}</TableCell>
            <TableCell className="text-muted-foreground max-w-64 truncate text-xs">
              {d.error ?? "—"}
            </TableCell>
            <TableCell className="text-muted-foreground whitespace-nowrap">
              {formatDate(d.created_at)}
            </TableCell>
            <TableCell className="text-right">
              {(d.status === "failed" || d.status === "exhausted") && (
                <button
                  className="text-primary text-xs font-medium hover:underline disabled:opacity-50"
                  disabled={mutation.isPending}
                  onClick={() => redeliver(d.id)}
                >
                  Redeliver
                </button>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
      </Table>
    </div>
  );
}

export function WebhooksPage() {
  const { result, query } = useWorkspaceList<WebhookSubscription>({ resource: "webhooks" });
  const { data: canManage } = useCan({ resource: "webhooks", action: "delete" });
  const [openId, setOpenId] = useState<string | null>(null);

  const rows = result?.data ?? [];

  return (
    <ListView>
      <ListViewHeader title="Webhooks">
        <CreateButton resource="webhooks">New webhook</CreateButton>
      </ListViewHeader>
      <div className="border-border overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>URL</TableHead>
              <TableHead>Events</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((sub) => (
              <Fragment key={sub.id}>
                <TableRow>
                  <TableCell>
                    <p className="flex items-center gap-2 font-medium">
                      <Webhook className="text-muted-foreground h-4 w-4" />
                      <span className="max-w-md truncate font-mono text-xs">
                        {sub.url}
                      </span>
                    </p>
                  </TableCell>
                  <TableCell>
                    <div className="flex max-w-64 flex-wrap gap-1">
                      {sub.events.map((e) => (
                        <Badge key={e} variant="outline" className="text-xs">
                          {e}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell>
                    {sub.active ? (
                      <Badge variant="success">active</Badge>
                    ) : (
                      <Badge variant="secondary">paused</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(sub.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        className="text-primary text-xs font-medium hover:underline"
                        onClick={() =>
                          setOpenId(openId === sub.id ? null : sub.id)
                        }
                      >
                        {openId === sub.id ? "Hide log" : "Delivery log"}
                      </button>
                      {canManage?.can && (
                        <DeleteButton
                          resource="webhooks"
                          recordItemId={sub.id}
                          variant="ghost"
                          size="sm"
                        />
                      )}
                    </div>
                  </TableCell>
                </TableRow>
                {openId === sub.id && (
                  <TableRow>
                    <TableCell colSpan={5}>
                      <DeliveryLog subscriptionId={sub.id} />
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            ))}
            {/* A request that failed is not a list that came back empty, and
                saying otherwise is what made a dead endpoint read as "no
                subscriptions". */}
            {query.isPending && rows.length === 0 && (
              <EmptyRow colSpan={5}>Loading…</EmptyRow>
            )}
            {query.isError && (
              <EmptyRow colSpan={5}>
                <span className="text-destructive">
                  Could not load webhook subscriptions:{" "}
                  {query.error?.message ?? "Unknown error"}
                </span>{" "}
                <Button variant="outline" size="sm" onClick={() => query.refetch()}>
                  Try again
                </Button>
              </EmptyRow>
            )}
            {!query.isPending && !query.isError && rows.length === 0 && (
              <EmptyRow colSpan={5}>No webhook subscriptions yet.</EmptyRow>
            )}
          </TableBody>
        </Table>
      </div>
    </ListView>
  );
}
