import { useCan } from "@refinedev/core";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ListView,
  ListViewHeader,
} from "../components/refine-ui/views/list-view";
import type { ProjectDemoItem } from "./types";

/**
 * Demo page proving the project extension seams. Static rows only — no
 * `dataProvider` call, so the demo is frontend-only with no backend impact.
 * Gated with `useCan` on the project resource exactly like a built-in
 * permission-gated page.
 */
const ROWS: ProjectDemoItem[] = [
  {
    id: "demo-1",
    name: "Example widget",
    status: "active",
    description: "First row contributed entirely from src/project/.",
  },
  {
    id: "demo-2",
    name: "Archived gadget",
    status: "archived",
    description: "Second row showing a non-active status variant.",
  },
];

export function DemoPage() {
  const { data: canView } = useCan({ resource: "project-demo", action: "list" });
  if (canView && !canView.can) {
    return (
      <div className="mx-auto max-w-2xl py-12 text-center">
        <h2 className="text-xl font-semibold">Access denied</h2>
        <p className="text-muted-foreground mt-2 text-sm">
          You do not have permission to view the project demo page.
        </p>
        <Button variant="outline" asChild className="mt-4">
          <Link to="/">Back to dashboard</Link>
        </Button>
      </div>
    );
  }
  return (
    <ListView>
      <ListViewHeader title="Project Demo" />
      <div className="border-border overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Description</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {ROWS.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-medium">{row.name}</TableCell>
                <TableCell>
                  <Badge variant={row.status === "active" ? "default" : "secondary"}>
                    {row.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">{row.description}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </ListView>
  );
}
